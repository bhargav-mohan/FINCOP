import { friendlyWarning } from "@/lib/format";

export function Warnings({ warnings }: { warnings: string[] }) {
  if (!warnings.length) {
    return null;
  }
  const messages = [...new Set(warnings.map(friendlyWarning).filter((msg): msg is string => Boolean(msg)))];
  if (!messages.length) {
    return null;
  }
  return (
    <aside className="rounded-uber border border-neutral-300 bg-white px-4 py-3 text-sm" role="status">
      <p className="font-medium text-ink">Heads up</p>
      <ul className="mt-1 list-disc space-y-1 pl-4 text-muted">
        {messages.map((msg) => (
          <li key={msg}>{msg}</li>
        ))}
      </ul>
    </aside>
  );
}
