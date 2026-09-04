export function ReviewSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true" aria-live="polite">
      <div>
        <p className="text-base font-semibold text-ink">Matching payments to your bank file…</p>
        <p className="mt-1 text-sm text-muted">This usually takes under a minute. Unmatched items stay open.</p>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="h-28 animate-pulse rounded-uber bg-line/70" />
        <div className="h-28 animate-pulse rounded-uber bg-line/70" />
        <div className="h-28 animate-pulse rounded-uber bg-line/70" />
      </div>
      <div className="h-20 animate-pulse rounded-uber bg-line/70" />
      <div className="h-48 animate-pulse rounded-uber bg-line/70" />
    </div>
  );
}
