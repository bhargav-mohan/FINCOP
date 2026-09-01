import { existsSync } from "node:fs";
import path from "node:path";

import { EvidenceTabs } from "@/components/EvidenceTabs";
import { ExceptionsTable } from "@/components/ExceptionsTable";
import { TopBar } from "@/components/TopBar";
import { Verdict } from "@/components/Verdict";
import { Warnings } from "@/components/Warnings";
import { friendlyError } from "@/lib/format";
import { repoRoot, runFinanceController } from "@/lib/runFinanceController";

type Search = {
  seed?: string;
  source?: string;
  uploadId?: string;
  useLlm?: string;
};

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

export const dynamic = "force-dynamic";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Search>;
}) {
  const params = await searchParams;
  const seed = Number(params.seed ?? 42);
  const safeSeed = Number.isFinite(seed) ? seed : 42;
  const uploadId = params.uploadId && isUuid(params.uploadId) ? params.uploadId : undefined;
  const uploadDir =
    params.source === "zip" && uploadId
      ? path.join(repoRoot(), "dashboard", ".uploads", uploadId)
      : undefined;
  const zipPath = uploadDir && existsSync(uploadDir) ? uploadDir : undefined;

  let data;
  try {
    data = runFinanceController({
      seed: safeSeed,
      numRecords: 80,
      zipPath,
      useLlm: params.useLlm === "1" || params.useLlm === "true",
    });
  } catch (err) {
    const raw = err instanceof Error ? err.message : "";
    return <TopBar error={friendlyError(raw)} seed={safeSeed} batchSource="generated" />;
  }

  if (data.error) {
    return <TopBar error={friendlyError(data.error)} seed={safeSeed} batchSource="generated" />;
  }

  return (
    <>
      <TopBar
        batchSource={data.batch_source}
        sourceFiles={data.source_files}
        seed={data.seed}
        data={data}
      />
      <Warnings
        warnings={[...(data.ingestion?.warnings ?? []), ...(data.agent_warnings ?? [])]}
      />
      <Verdict data={data} />
      <ExceptionsTable
        rows={data.exceptions}
        title={`Needs a person (${data.exceptions.length})`}
        batchKey={data.store?.batch_key}
        totalExposure={data.total_exposure}
      />
      <EvidenceTabs data={data} />
    </>
  );
}
