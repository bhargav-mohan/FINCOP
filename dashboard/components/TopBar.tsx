"use client";

import { useState } from "react";

import { ActionsBar } from "@/components/ActionsBar";
import { SourceBadge } from "@/components/SourceBadge";
import { ZipUpload } from "@/components/ZipUpload";
import { Button } from "@/components/ui/Button";
import type { BatchSource, DashboardRun } from "@/lib/types";

export function TopBar({
  batchSource,
  sourceFiles,
  error,
  data,
  processing = false,
}: {
  batchSource?: BatchSource;
  sourceFiles?: Record<string, string>;
  error?: string;
  data?: DashboardRun;
  processing?: boolean;
}) {
  const [uploadOpen, setUploadOpen] = useState(!data && !processing);
  const empty = !data && !processing;

  return (
    <div className="sticky top-0 z-20 -mx-4 -mt-6 border-b border-line bg-wash/90 px-4 py-4 backdrop-blur sm:-mt-10">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <header className="max-w-xl space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Settlement review</h1>
          <p className="text-sm text-muted">
            {processing
              ? "Matching payments to your bank file. Stay on this page."
              : data
                ? "We matched what we could. Anything left needs a person."
                : "Drop payments, settlements, and the bank file. We match them. You only see leftovers."}
          </p>
          {batchSource ? <SourceBadge batchSource={batchSource} sourceFiles={sourceFiles} /> : null}
        </header>
        <div className="flex flex-wrap items-center gap-3">
          <ActionsBar data={data} />
          {data ? (
            <Button variant="secondary" onClick={() => setUploadOpen((v) => !v)}>
              {uploadOpen ? "Hide new files" : "Review new files"}
            </Button>
          ) : null}
        </div>
      </div>
      {uploadOpen && !processing ? (
        <div className={empty ? "mt-6" : "mt-4"}>
          <ZipUpload compact={!empty} />
        </div>
      ) : null}
      {error ? (
        <p className="mt-3 text-sm text-red-700" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
