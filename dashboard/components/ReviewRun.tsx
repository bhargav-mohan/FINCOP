import { connection } from "next/server";
import { unstable_noStore as noStore } from "next/cache";

import { CashBooks } from "@/components/CashBooks";
import { EvidenceTabs } from "@/components/EvidenceTabs";
import { ExceptionsTable } from "@/components/ExceptionsTable";
import { KpiStrip } from "@/components/KpiStrip";
import { TopBar } from "@/components/TopBar";
import { Verdict } from "@/components/Verdict";
import { Warnings } from "@/components/Warnings";
import { friendlyError } from "@/lib/format";
import { runFinanceController } from "@/lib/runFinanceController";

export async function ReviewRun({
  zipPath,
  useLlm,
  requestId,
}: {
  zipPath: string;
  useLlm: boolean;
  requestId: string;
}) {
  noStore();
  await connection();
  let data;
  try {
    data = await runFinanceController({ zipPath, useLlm });
  } catch (err) {
    const raw = err instanceof Error ? err.message : "";
    return <TopBar error={friendlyError(raw)} />;
  }

  if (data.error) {
    return <TopBar error={friendlyError(data.error)} />;
  }

  return (
    <>
      <TopBar
        batchSource={data.batch_source}
        sourceFiles={data.source_files}
        data={data}
      />
      <Warnings
        warnings={[...(data.ingestion?.warnings ?? []), ...(data.agent_warnings ?? [])]}
      />
      <Verdict data={data} />
      <CashBooks data={data} />
      <KpiStrip data={data} />
      <ExceptionsTable
        key={requestId}
        rows={data.exceptions}
        title={`Needs you (${data.exceptions.length})`}
        batchKey={data.store?.batch_key}
        totalExposure={data.total_exposure}
      />
      <EvidenceTabs key={requestId} data={data} />
    </>
  );
}
