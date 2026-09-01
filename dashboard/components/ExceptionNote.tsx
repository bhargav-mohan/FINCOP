"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { DashboardException } from "@/lib/types";

export function ExceptionNote({
  row,
  batchKey,
}: {
  row: DashboardException;
  batchKey?: string;
}) {
  const router = useRouter();
  const [note, setNote] = useState(row.note ?? "");
  const [assignee, setAssignee] = useState(row.assignee ?? "");
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);
  if (!batchKey || !row.key) {
    return null;
  }

  async function post(action: "note" | "resolve") {
    setPending(true);
    setStatus("");
    try {
      const res = await fetch("/api/note", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action,
          batchKey,
          exceptionKey: row.key,
          note,
          assignee,
          author: "analyst",
        }),
      });
      if (!res.ok) {
        setStatus("Could not save.");
        return;
      }
      setStatus(action === "resolve" ? "Marked resolved." : "Saved.");
      router.refresh();
    } catch {
      setStatus("Could not save.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      className="space-y-2 rounded border border-slate-200 bg-white p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void post("note");
      }}
    >
      <p className="text-xs font-medium text-slate-700">Analyst note</p>
      {row.resolved_at ? (
        <p className="text-xs text-emerald-800">Resolved {row.resolved_at.slice(0, 10)}</p>
      ) : null}
      <input
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
        placeholder="Assignee"
        value={assignee}
        onChange={(e) => setAssignee(e.target.value)}
      />
      <textarea
        className="w-full rounded border border-slate-300 px-2 py-1 text-sm"
        rows={2}
        placeholder="What did you check?"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={pending}
          className="rounded bg-slate-900 px-3 py-1 text-xs font-medium text-white disabled:opacity-60"
        >
          Save note
        </button>
        <button
          type="button"
          disabled={pending}
          className="rounded border border-slate-300 px-3 py-1 text-xs font-medium text-slate-800 disabled:opacity-60"
          onClick={() => void post("resolve")}
        >
          Mark resolved
        </button>
        {status ? <span className="text-xs text-slate-500">{status}</span> : null}
      </div>
    </form>
  );
}
