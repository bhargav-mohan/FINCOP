"use client";

import { humanizeDecision, humanizeSource } from "@/lib/format";
import type { DashboardRun } from "@/lib/types";

import { Disclosure } from "./ui/Disclosure";
import { Panel } from "./ui/Panel";
import { Section } from "./ui/Section";

const PREVIEW = 8;

export function ReviewTimeline({
  items,
}: {
  items: NonNullable<DashboardRun["investigations"]>;
}) {
  if (!items.length) {
    return (
      <Panel className="p-4">
        <h2 className="text-sm font-medium text-slate-700">Review activity</h2>
        <p className="mt-1 text-xs text-slate-500">Each decision the review made, in order.</p>
        <p className="mt-2 text-sm text-slate-500">No manual review needed.</p>
      </Panel>
    );
  }
  return (
    <Section title={`Review activity (${items.length})`} subtitle="Each decision the review made, in order.">
      <Disclosure preview={PREVIEW} total={items.length}>
        {(expanded) => {
          const visible = expanded ? items : items.slice(0, PREVIEW);
          return (
            <ul className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200 bg-white">
              {visible.map((item, index) => (
                <li key={`${item.id}-${index}`} className="px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-medium text-slate-800">{item.id}</span>
                    <span className="text-slate-700">{humanizeDecision(item.decision)}</span>
                    <span className="text-xs text-slate-500">{humanizeSource(item.by)}</span>
                  </div>
                  {item.rationale ? <p className="mt-1 text-slate-600">{item.rationale}</p> : null}
                </li>
              ))}
            </ul>
          );
        }}
      </Disclosure>
    </Section>
  );
}
