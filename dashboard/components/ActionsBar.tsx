"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useTransition } from "react";

import type { DashboardRun } from "@/lib/types";

import { Button } from "./ui/Button";
import { DownloadReport } from "./DownloadReport";

function ActionsBarInner({ data }: { data?: DashboardRun }) {
  const router = useRouter();
  const params = useSearchParams();
  const [pending, startTransition] = useTransition();
  const uploadId = params.get("uploadId");
  const uploaded = Boolean(data) && params.get("source") === "zip" && Boolean(uploadId);

  return (
    <div className="flex flex-wrap items-center gap-3">
      {uploaded ? (
        <Button
          disabled={pending}
          onClick={() => {
            startTransition(() => {
              const next = new URLSearchParams();
              next.set("source", "zip");
              next.set("uploadId", uploadId as string);
              const useLlm = params.get("useLlm");
              if (useLlm) {
                next.set("useLlm", useLlm);
              }
              next.set("run", String(Date.now()));
              router.push(`/?${next.toString()}`);
            });
          }}
        >
          {pending ? "Running again…" : "Run this file again"}
        </Button>
      ) : null}
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
