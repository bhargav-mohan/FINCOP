import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

import type { DashboardRun } from "./types";

export function repoRoot(): string {
  const cwd = process.cwd();
  if (existsSync(path.join(cwd, "src", "finance_controller"))) {
    return cwd;
  }
  const parent = path.join(cwd, "..");
  if (existsSync(path.join(parent, "src", "finance_controller"))) {
    return parent;
  }
  throw new Error("Could not find finance_controller repo root");
}

function pythonBin(root: string): string {
  const venv = path.join(root, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

export { pythonBin };

export function runFinanceController(opts: {
  seed: number;
  numRecords: number;
  zipPath?: string;
  useLlm?: boolean;
  matchTax?: boolean;
}): DashboardRun {
  const root = repoRoot();
  const args = [
    "-m",
    "finance_controller.run_finance_controller",
    "--seed",
    String(opts.seed),
    "--num-records",
    String(opts.numRecords),
  ];
  if (opts.zipPath) {
    args.push("--zip", opts.zipPath);
  }
  if (opts.useLlm) {
    args.push("--use-llm");
  }
  if (opts.matchTax === false) {
    args.push("--no-tax");
  }
  const result = spawnSync(pythonBin(root), args, {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(root, "src") },
    timeout: opts.useLlm ? 180_000 : 60_000,
  });
  if (result.error) {
    throw result.error;
  }
  let payload: DashboardRun;
  try {
    const stdout = result.stdout || "";
    const start = stdout.indexOf("{");
    const end = stdout.lastIndexOf("}");
    if (start < 0 || end <= start) {
      throw new Error("no JSON");
    }
    payload = JSON.parse(stdout.slice(start, end + 1)) as DashboardRun;
  } catch {
    throw new Error(result.stderr || `controller exited ${result.status}`);
  }
  if (payload.error) {
    throw new Error(payload.error);
  }
  if (result.status !== 0) {
    throw new Error(result.stderr || `controller exited ${result.status}`);
  }
  return payload;
}
