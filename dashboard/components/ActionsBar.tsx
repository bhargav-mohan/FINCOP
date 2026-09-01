"use client";

import { useRouter } from "next/navigation";
import { Suspense, useTransition } from "react";

import type { DashboardRun } from "@/lib/types";

import { DownloadReport } from "./DownloadReport";

function ActionsBarInner({ data }: { data?: DashboardRun }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        disabled={pending}
        className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
        onClick={() => {
          startTransition(() => {
            router.push(`/?seed=${Math.floor(Math.random() * 1_000_000)}`);
          });
        }}
      >
        {pending ? "Running review..." : "Run again"}
      </button>
      {data ? <DownloadReport data={data} /> : null}
    </div>
  );
}

export function ActionsBar({ data }: { data?: DashboardRun }) {
  return (
    <Suspense fallback={<div className="h-10" />}>
      <ActionsBarInner data={data} />
    </Suspense>
  );
}
