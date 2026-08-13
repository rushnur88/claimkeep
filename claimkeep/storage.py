"""Private, atomic, append-safe writes for everything ClaimKeep keeps.

Three properties, each learned from a way this can go wrong:

**Private.** A brief is a verbatim slice of a session. Redaction masks the shapes
it knows about, which is defence in depth rather than a guarantee, so the file
itself must not be readable by every account on the box. Under a 022 umask these
were landing as 0755 directories and 0644 files.

**Atomic.** Rewriting a brief in place means a crash between truncate and write
leaves a truncated file exactly where the previous brief was, and the next
SessionStart reads it. Writing beside the target and renaming means a reader sees
either the old brief or the new one, never a half of either.

**Append-safe.** The lesson store and the probe log are append-only and are
written by whichever hook fires — several agents can share one store. An
interleaved write corrupts a JSONL line for good, so appends take an advisory
lock where the platform has one.

Stdlib only, and every failure here is the caller's to report: this module does
not swallow errors, because the layers above it decide what is fatal.
"""

from __future__ import annotations

import os
import tempfile
from typing import Optional

try:  # POSIX advisory locking; absent on Windows, where we degrade to no lock.
    import fcntl
except ImportError:  # pragma: no cover - platform dependent
    fcntl = None  # type: ignore[assignment]

DIR_MODE = 0o700
FILE_MODE = 0o600


def private_dir(path: Optional[str]) -> None:
    """Create `path` if needed and make it owner-only.

    `os.makedirs(mode=...)` is not enough: the mode applies to the final
    component only and is masked by the umask, which is exactly the thing that
    produced 0755 here.
    """
    if not path:
        return
    os.makedirs(path, exist_ok=True)
    try:
        os.chmod(path, DIR_MODE)
    except OSError:
        # A directory we do not own — the caller still gets to use it.
        pass


def write_private(path: str, text: str) -> None:
    """Write `text` to `path` atomically, owner-only.

    The temporary file is created in the destination directory so the rename
    stays on one filesystem, and is removed if anything fails, so a failed write
    leaves neither a partial brief nor litter.
    """
    path = os.path.abspath(os.path.expanduser(path))
    directory = os.path.dirname(path)
    private_dir(directory)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".claimkeep-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, FILE_MODE)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_private(path: str, text: str) -> None:
    """Append `text` to `path`, owner-only, under an advisory lock if available."""
    path = os.path.abspath(os.path.expanduser(path))
    private_dir(os.path.dirname(path))
    existed = os.path.exists(path)
    with open(path, "a", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(text)
            handle.flush()
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    if not existed:
        try:
            os.chmod(path, FILE_MODE)
        except OSError:
            pass
