#!/usr/bin/env node
const { spawnSync } = require("child_process");
const path = require("path");

const packageRoot = path.resolve(__dirname, "..");
const pythonPath = [packageRoot, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter);

function run(command, args) {
  return spawnSync(command, args, {
    stdio: "inherit",
    env: { ...process.env, PYTHONPATH: pythonPath },
  });
}

let child = run("python3", ["-m", "claimkeep", ...process.argv.slice(2)]);
if (child.error && child.error.code === "ENOENT") {
  child = run("claimkeep", process.argv.slice(2));
}
if (child.error) {
  console.error(child.error.message);
  process.exit(1);
}
process.exit(child.status === null ? 1 : child.status);
