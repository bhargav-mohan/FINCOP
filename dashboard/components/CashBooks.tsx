import { formatInr } from "@/lib/format";
import type { DashboardRun } from "@/lib/types";

import { Panel } from "./ui/Panel";

export function CashBooks({ data }: { data: DashboardRun }) {
  const cash = data.cash;
  const rows = [
    {
      label: "Settled in bank",
      amount: cash.closed_bank_net,
      hint: "Closed loops — bank credit we booked",
    },
    {
      label: "Blocked on exceptions",
      amount: cash.in_flight_amount,
      hint: `${cash.in_flight_count ?? data.exception_count} open items, ledger gross`,
    },
    {
      label: "Expected, not credited",
      amount: cash.expected_not_credited ?? "0.00",
      hint: "Books with no bank row in the group",
    },
    {
      label: "Bank unmatched",
      amount: cash.unmatched_bank_net ?? "0.00",
      hint: "Statement credits the engine did not close",
    },
  ];
  const expected = cash.expected_ledger_gross ?? "0.00";
  const credited = cash.bank_credited_total ?? "0.00";
  const variance = cash.variance ?? "0.00";
  const unmatched = cash.unmatched_bank_net ?? "0.00";
  const blocked = cash.in_flight_amount ?? "0.00";
  const settledLedger = Number(cash.settled_ledger_gross ?? "0");
  const settledBank = Number(cash.closed_bank_net);
  const expectedNum = Number(expected);
  const blockedNum = Number(blocked);
  const ledgerOfClosed =
    Number.isFinite(settledLedger) && settledLedger > 0
      ? settledLedger
      : expectedNum - blockedNum;
  const feesOnClosed = ledgerOfClosed - settledBank;

  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-ink">The batch in rupees</h2>
        <p className="mt-0.5 text-sm text-muted">
          Record counts treat a ₹200 timing break and a ₹90,000 amount break as one each. This
          view is the queue to work first.
        </p>
      </div>
      <Panel className="grid gap-6 p-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="grid grid-cols-2 gap-4">
          {rows.map((row) => (
            <div key={row.label}>
              <p className="text-sm text-muted">{row.label}</p>
              <p className="mt-0.5 text-lg font-semibold tabular-nums text-ink">
                {formatInr(row.amount)}
              </p>
              <p className="mt-1 text-xs text-muted">{row.hint}</p>
            </div>
          ))}
        </div>
        <div>
          <p className="text-sm text-muted">Ledger expected vs bank credited</p>
          <p className="mt-0.5 text-lg font-semibold tabular-nums text-ink">
            {formatInr(expected)} vs {formatInr(credited)}
          </p>
          <p className="mt-1 text-xs text-muted">
            Bank credited includes unmatched statement rows; Settled in bank is closed loops only.
            They differ by Bank unmatched ({formatInr(unmatched)}).
          </p>
          <p className="mt-1 text-xs text-muted">
            Settled + expected-not-credited + blocked do not add to ledger expected:
            expected-not-credited is already inside blocked, and Settled is bank net after fees.
            The leftover is fees on closed loops ({formatInr(feesOnClosed)}), not a hidden break.
          </p>
          <p className="mt-1 text-xs text-muted">
            Variance {formatInr(variance)}. Unknown ingest amounts are excluded, not counted as
            zero.
          </p>
          {data.forward ? (
            <p className="mt-3 text-sm text-muted">
              Forward (lag {data.forward.lag_days} banking days from {data.forward.as_of}): due{" "}
              {formatInr(data.forward.due_within_window)}, stuck past window{" "}
              {formatInr(data.forward.stuck_past_window)}.
            </p>
          ) : null}
        </div>
      </Panel>
    </section>
  );
}
