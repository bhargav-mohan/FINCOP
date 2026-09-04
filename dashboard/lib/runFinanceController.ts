import { existsSync } from "node:fs";
import { spawn } from "node:child_process";
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

type Spawned = {
  status: number | null;
  stdout: string;
  stderr: string;
  error?: Error;
};

function spawnPython(args: string[], timeoutMs?: number): Promise<Spawned> {
  const root = repoRoot();
  return new Promise((resolve) => {
    const child = spawn(pythonBin(root), args, {
      cwd: root,
      env: { ...process.env, PYTHONPATH: path.join(root, "src") },
    });
    let stdout = "";
    let stderr = "";
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = (result: Spawned) => {
      if (settled) {
        return;
      }
      settled = true;
      if (timer) {
        clearTimeout(timer);
      }
      resolve(result);
    };
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });
    if (timeoutMs != null) {
      timer = setTimeout(() => {
        child.kill("SIGKILL");
        finish({
          status: null,
          stdout,
          stderr,
          error: new Error(`controller timed out after ${timeoutMs}ms`),
        });
      }, timeoutMs);
    }
    child.on("error", (error) => finish({ status: null, stdout, stderr, error }));
    child.on("close", (status) => finish({ status, stdout, stderr }));
  });
}

function parsePayload(stdout: string, stderr: string, status: number | null): DashboardRun {
  const start = stdout.indexOf("{");
  const end = stdout.lastIndexOf("}");
  if (start < 0 || end <= start) {
    throw new Error(stderr || `controller exited ${status}`);
  }
  return JSON.parse(stdout.slice(start, end + 1)) as DashboardRun;
}

export async function runFinanceController(opts: {
  zipPath?: string;
  dataDir?: string;
  useLlm?: boolean;
  matchTax?: boolean;
}): Promise<DashboardRun> {
  const useLlm = opts.useLlm !== false;
  if (!opts.zipPath && !opts.dataDir) {
    throw new Error("Upload a file to run a review.");
  }
  const args = ["-m", "finance_controller.run_finance_controller"];
  if (opts.zipPath) {
    args.push("--zip", opts.zipPath);
  }
  if (opts.dataDir) {
    args.push("--data-dir", opts.dataDir);
  }
  if (!useLlm) {
    args.push("--no-llm");
  }
  if (opts.matchTax === false) {
    args.push("--no-tax");
  }
  const result = await spawnPython(args, useLlm ? undefined : 60_000);
  if (result.error) {
    throw result.error;
  }
  let payload: DashboardRun;
  try {
    payload = parsePayload(result.stdout || "", result.stderr || "", result.status);
  } catch (err) {
    if (err instanceof Error && !err.message.startsWith("controller exited")) {
      throw new Error(result.stderr || `controller exited ${result.status}`);
    }
    throw err;
  }
  if (payload.error) {
    throw new Error(payload.error);
  }
  if (result.status !== 0) {
    throw new Error(result.stderr || `controller exited ${result.status}`);
  }
  return payload;
}
