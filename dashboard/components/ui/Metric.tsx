export function Metric({
  label,
  value,
  hint,
  title,
  className = "min-w-[7rem]",
}: {
  label: string;
  value: string;
  hint?: string;
  title?: string;
  className?: string;
}) {
  return (
    <div className={className} title={title}>
      <p className="text-sm text-muted">{label}</p>
      <p className="mt-0.5 text-lg font-semibold tabular-nums text-ink">{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted">{hint}</p> : null}
    </div>
  );
}
