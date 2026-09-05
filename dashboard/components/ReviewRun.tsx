import { CashBooks } from "@/components/CashBooks";
import { EvidenceTabs } from "@/components/EvidenceTabs";
import { ExceptionsTable } from "@/components/ExceptionsTable";
import { TopBar } from "@/components/TopBar";
import { MountOnce } from "@/components/ui/MountOnce";
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
    <MountOnce name={`review:${requestId}`}>
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
      <ExceptionsTable
        rows={data.exceptions}
        title={`Needs you (${data.exceptions.length})`}
        batchKey={data.store?.batch_key}
        totalExposure={data.total_exposure}
      />
      <EvidenceTabs data={data} />
    </MountOnce>
  );
}
