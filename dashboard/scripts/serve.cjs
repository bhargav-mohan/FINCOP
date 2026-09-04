#!/usr/bin/env node
/**
 * Serve the dashboard without webpack HMR.
 * Chrome logs "WebSocket is closed due to suspension" against
 * ws://localhost:3000/_next/webpack-hmr whenever the tab sleeps; that socket
 * only exists in `next dev`. `next start` has no HMR.
 *
 * Rebuilds when app/component sources are newer than .next/BUILD_ID so a
 * reviewer never sees a stale match-rate (the 82.5% vs 70.89% split).
 */
const { existsSync, readdirSync, statSync } = require("node:fs");
const { spawnSync } = require("node:child_process");
const path = require("node:path");

const root = path.join(__dirname, "..");
const nextBin = path.join(root, "node_modules", ".bin", "next");
const buildIdPath = path.join(root, ".next", "BUILD_ID");

function mtime(p) {
  try {
    return statSync(p).mtimeMs;
  } catch {
    return 0;
  }
}

function latestMtime(dir) {
  let latest = 0;
  if (!existsSync(dir)) {
    return 0;
  }
  for (const ent of readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name === ".next" || ent.name === ".uploads") {
      continue;
    }
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) {
      latest = Math.max(latest, latestMtime(p));
    } else {
      latest = Math.max(latest, mtime(p));
    }
  }
  return latest;
}

function run(args) {
  const result = spawnSync(nextBin, args, { cwd: root, stdio: "inherit", shell: false });
  process.exit(result.status === null ? 1 : result.status);
}

const sourceMtime = Math.max(
  latestMtime(path.join(root, "app")),
  latestMtime(path.join(root, "components")),
  latestMtime(path.join(root, "lib")),
  mtime(path.join(root, "next.config.js")),
  mtime(path.join(root, "tailwind.config.js")),
  mtime(path.join(root, "package.json"))
);
const stale = !existsSync(buildIdPath) || sourceMtime > mtime(buildIdPath);
if (stale) {
  const build = spawnSync(nextBin, ["build"], { cwd: root, stdio: "inherit", shell: false });
  if (build.status !== 0) {
    process.exit(build.status === null ? 1 : build.status);
  }
}
run(["start", "-p", "3000"]);
