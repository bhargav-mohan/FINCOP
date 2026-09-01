"use client";

import { useState } from "react";

import { ActionsBar } from "@/components/ActionsBar";
import { SourceBadge } from "@/components/SourceBadge";
import { ZipUpload } from "@/components/ZipUpload";
import type { BatchSource, DashboardRun } from "@/lib/types";

export function TopBar({
  batchSource,
  sourceFiles,
  seed,
  error,
  data,
}: {
  batchSource?: BatchSource;
  sourceFiles?: Record<string, string>;
  seed?: number;
  error?: string;
  data?: DashboardRun;
}) {
  const [uploadOpen, setUploadOpen] = useState(false);
  const generated = !batchSource || batchSource === "generated";
  const repro =
    generated && seed != null
      ? `Seed ${seed} · same seed reproduces this batch`
      : "Same file reproduces this review";

  return (
    <div className="sticky top-0 z-20 -mx-4 -mt-8 border-b border-slate-200 bg-slate-50/85 px-4 py-3 backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <header className="space-y-1">
          <h1 className="text-2xl font-semibold">Settlement review</h1>
          <p className="text-sm text-slate-500">
            Match payments to bank credits and list anything that still needs a person.
          </p>
          <p className="text-xs text-slate-500">{repro}</p>
          {batchSource ? <SourceBadge batchSource={batchSource} sourceFiles={sourceFiles} /> : null}
        </header>
        <div className="flex flex-wrap items-center gap-3">
          <ActionsBar data={data} />
          <button
            type="button"
            className="rounded border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-800"
            onClick={() => setUploadOpen((v) => !v)}
          >
            {uploadOpen ? "Hide upload" : "Upload"}
          </button>
        </div>
      </div>
      {uploadOpen ? <div className="mt-3">{<ZipUpload />}</div> : null}
      {error ? <p className="mt-2 text-sm text-red-600">{error}</p> : null}
    </div>
  );
}
