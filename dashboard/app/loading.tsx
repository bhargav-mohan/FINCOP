export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="h-7 w-56 rounded bg-slate-200" />
        <div className="h-4 w-96 max-w-full rounded bg-slate-200" />
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="h-28 rounded-lg bg-slate-200" />
        <div className="h-28 rounded-lg bg-slate-200" />
        <div className="h-28 rounded-lg bg-slate-200" />
      </div>
      <div className="h-20 rounded-lg bg-slate-200" />
      <div className="h-48 rounded-lg bg-slate-200" />
      <p className="text-sm text-slate-500">
        Running review… leftovers are sent to Gemini when a key is set.
      </p>
    </div>
  );
}
