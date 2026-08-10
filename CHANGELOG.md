# Changelog

## 0.2.0 — 2026-08-10

Installation fix. `claude plugin install claimkeep` now actually works on its own.

- **Fixed: plugin install was a silent no-op.** The plugin was declared as the `plugins/claimkeep`
  subdirectory while the Python package lived at the repository root, so the installed plugin had
  nothing to run. The hooks printed `No module named claimkeep`, exited `0`, and wrote no brief —
  a green install that did nothing. The repository root is now the plugin itself: manifest at
  `.claude-plugin/plugin.json`, hooks at `hooks/hooks.json`, scripts at `scripts/`.
- **Fixed: hooks required a separate `pip install`.** They now export `PYTHONPATH` from
  `CLAUDE_PLUGIN_ROOT` and run the bundled package in place. An installed `claimkeep` binary is
  still preferred when present.
- Removed the `plugins/` tree; `package.json` `files` updated accordingly.
- README rewritten to three blocks — what it is, how to install, how to verify — with production
  numbers and a copy-paste verification that exercises both hooks.

## 0.1.0 — 2026-06-21

Initial release: brief schema, calibration and regex-floor harvesters, redaction, rehydration,
CLI, benchmark scorer, and control/treatment probe logging.
