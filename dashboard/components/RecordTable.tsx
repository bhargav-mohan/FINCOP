import { formatInr, humanizeType } from "@/lib/format";
import type { DashboardRecord } from "@/lib/types";

export function RecordTable({ records }: { records: DashboardRecord[] }) {
  if (!records.length) {
    return <p className="text-xs text-slate-500">No source rows attached.</p>;
  }
  return (
    <div className="overflow-x-auto rounded border border-slate-200 bg-white">
      <table className="min-w-full text-left text-xs">
        <thead className="bg-slate-50 text-slate-500">
          <tr>
            <th className="px-2 py-1 font-medium">Source</th>
            <th className="px-2 py-1 font-medium">Reference</th>
            <th className="px-2 py-1 font-medium">Amount</th>
            <th className="px-2 py-1 font-medium">Date</th>
            <th className="px-2 py-1 font-medium">UTR</th>
            <th className="px-2 py-1 font-medium">Status</th>
            <th className="px-2 py-1 font-medium">Narration</th>
          </tr>
        </thead>
        <tbody>
          {records.map((row) => (
            <tr key={row.id} className="border-t border-slate-100">
              <td className="px-2 py-1">{humanizeType(row.source)}</td>
              <td className="px-2 py-1">{row.reference}</td>
              <td className="px-2 py-1 tabular-nums">
                {formatInr(row.amount)} {row.currency}
              </td>
              <td className="px-2 py-1">{row.date}</td>
              <td className="px-2 py-1">{row.utr || "—"}</td>
              <td className="px-2 py-1">{row.status}</td>
              <td className="px-2 py-1 text-slate-600">{row.description || row.payee || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
