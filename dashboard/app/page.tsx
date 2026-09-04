import { existsSync } from "node:fs";
import path from "node:path";
import { Suspense } from "react";
import { connection } from "next/server";
import { unstable_noStore as noStore } from "next/cache";

import { ReviewPending } from "@/components/ReviewPending";
import { ReviewRun } from "@/components/ReviewRun";
import { TopBar } from "@/components/TopBar";
import { repoRoot } from "@/lib/runFinanceController";

type Search = {
  source?: string | string[];
  uploadId?: string | string[];
  useLlm?: string | string[];
  n?: string | string[];
  run?: string | string[];
};

function first(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) {
    return value[0];
  }
  return value;
}

function isUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
}

export const dynamic = "force-dynamic";
export const revalidate = 0;
export const fetchCache = "force-no-store";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<Search>;
}) {
  noStore();
  await connection();
  const params = await searchParams;
  const source = first(params.source);
  const rawId = first(params.uploadId);
  const uploadId = rawId && isUuid(rawId) ? rawId : undefined;
  const uploadRequested = source === "zip" && Boolean(uploadId);
  const uploadDir = uploadRequested
    ? path.join(repoRoot(), "dashboard", ".uploads", uploadId as string)
    : undefined;
  const zipPath = uploadDir && existsSync(uploadDir) ? uploadDir : undefined;

  if (!zipPath) {
    return (
      <TopBar
        error={
          uploadRequested
            ? "That upload is no longer on this machine. Upload the files again."
            : undefined
        }
      />
    );
  }

  const useLlmRaw = first(params.useLlm);
  const useLlm = useLlmRaw !== "0" && useLlmRaw !== "false";
  const requestId = `${uploadId}:${first(params.n) || first(params.run) || "0"}`;
  return (
    <Suspense key={requestId} fallback={<ReviewPending />}>
      <ReviewRun zipPath={zipPath} useLlm={useLlm} requestId={requestId} />
    </Suspense>
  );
}
