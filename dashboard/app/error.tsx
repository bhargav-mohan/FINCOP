"use client";

import { Button } from "@/components/ui/Button";

export default function ErrorPage({
  error: _error,
}: {
  error: Error & { digest?: string };
}) {
  return (
    <section className="rounded-uber border border-line bg-white p-5">
      <h1 className="text-lg font-semibold text-ink">Something went wrong</h1>
      <p className="mt-2 text-sm text-muted">
        Try the review again, or upload CSVs, a folder, Excel, or a ZIP.
      </p>
      <div className="mt-4">
        <Button onClick={() => window.location.assign("/")}>Back to upload</Button>
      </div>
    </section>
  );
}
