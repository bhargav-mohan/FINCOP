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
    <aside className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <ul className="list-disc space-y-1 pl-4">
        {messages.map((msg) => (
          <li key={msg}>{msg}</li>
        ))}
      </ul>
    </aside>
  );
}
