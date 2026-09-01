"use client";

export default function ErrorPage({
  error: _error,
}: {
  error: Error & { digest?: string };
}) {
  return (
    <section className="rounded-lg border border-red-200 bg-white p-4">
      <h1 className="text-lg font-semibold">Something went wrong</h1>
      <p className="mt-2 text-sm text-slate-600">Please try again, or upload CSVs, a folder, Excel, or a ZIP.</p>
    </section>
  );
}
