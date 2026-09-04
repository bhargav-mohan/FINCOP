"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { DashboardException } from "@/lib/types";

import { Button } from "./ui/Button";

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
        setStatus("Could not save. Try again.");
        return;
      }
      setStatus(action === "resolve" ? "Marked done." : "Saved.");
      router.refresh();
    } catch {
      setStatus("Could not save. Try again.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form
      className="space-y-2 rounded-uber border border-line bg-white p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void post("note");
      }}
    >
      <p className="text-sm font-medium text-ink">Your note</p>
      {row.resolved_at ? (
        <p className="text-xs text-ok">Resolved {row.resolved_at.slice(0, 10)}</p>
      ) : null}
      <input
        className="w-full rounded-uber border border-line px-3 py-2 text-sm"
        placeholder="Who is looking at this?"
        value={assignee}
        onChange={(e) => setAssignee(e.target.value)}
      />
      <textarea
        className="w-full rounded-uber border border-line px-3 py-2 text-sm"
        rows={2}
        placeholder="What did you check?"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={pending}>
          Save note
        </Button>
        <Button variant="secondary" disabled={pending} onClick={() => void post("resolve")}>
          Mark done
        </Button>
        {status ? (
          <span className="text-xs text-muted" role="status">
            {status}
          </span>
        ) : null}
      </div>
    </form>
  );
}
