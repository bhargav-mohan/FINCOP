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
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 font-semibold tabular-nums text-slate-900">{value}</p>
      {hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
    </div>
  );
}
