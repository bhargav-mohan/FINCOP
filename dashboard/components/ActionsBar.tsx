"use client";

import type { DashboardRun } from "@/lib/types";

import { Button } from "./ui/Button";
import { DownloadReport } from "./DownloadReport";

export function ActionsBar({ data }: { data?: DashboardRun }) {
  const uploaded = Boolean(data) && data.batch_source !== "generated";

  return (
    <div className="flex flex-wrap items-center gap-3">
      {uploaded ? (
        <Button
          onClick={() => {
            const params = new URLSearchParams(window.location.search);
            const uploadId = params.get("uploadId");
            if (!uploadId) {
              return;
            }
            const next = new URLSearchParams();
            next.set("source", "zip");
            next.set("uploadId", uploadId);
            const useLlm = params.get("useLlm");
            if (useLlm) {
              next.set("useLlm", useLlm);
            }
            next.set("run", String(Date.now()));
            window.location.assign(`/?${next.toString()}`);
          }}
        >
          Run this file again
        </Button>
      ) : null}
      {data ? <DownloadReport data={data} /> : null}
    </div>
  );
}
