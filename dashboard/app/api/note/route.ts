import { spawnSync } from "node:child_process";
import path from "node:path";

import { pythonBin, repoRoot } from "@/lib/runFinanceController";

export async function POST(request: Request) {
  let body: {
    action?: string;
    batchKey?: string;
    exceptionKey?: string;
    note?: string;
    assignee?: string;
    author?: string;
  };
  try {
    body = await request.json();
  } catch {
    return new Response("invalid json", { status: 400 });
  }
  const action = body.action ?? "note";
  if (action !== "note" && action !== "resolve") {
    return new Response("action must be note or resolve", { status: 400 });
  }
  const batchKey = body.batchKey ?? "";
  const exceptionKey = body.exceptionKey ?? "";
  if (!batchKey || !exceptionKey) {
    return new Response("batchKey and exceptionKey required", { status: 400 });
  }
  const root = repoRoot();
  const args = [
    "-m",
    "finance_controller.store.cli",
    action,
    "--batch-key",
    batchKey,
    "--exception-key",
    exceptionKey,
    "--author",
    body.author || "analyst",
    // Sent for both actions: resolving with unsaved text must not discard it.
    "--note",
    body.note || "",
    "--assignee",
    body.assignee || "",
  ];
  const result = spawnSync(pythonBin(root), args, {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, PYTHONPATH: path.join(root, "src") },
    timeout: 15_000,
  });
  if (result.status !== 0) {
    return new Response(result.stderr || "store write failed", { status: 500 });
  }
  return Response.json({ ok: true });
}
