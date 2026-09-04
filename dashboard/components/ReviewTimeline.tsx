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
        <h2 className="text-base font-semibold text-ink">What we did</h2>
        <p className="mt-1 text-sm text-muted">Each decision, in order.</p>
        <p className="mt-2 text-sm text-muted">No extra review was needed.</p>
      </Panel>
    );
  }
  return (
    <Section title={`What we did (${items.length})`} subtitle="Each decision, in order.">
      <Disclosure preview={PREVIEW} total={items.length}>
        {(expanded) => {
          const visible = expanded ? items : items.slice(0, PREVIEW);
          return (
            <ul className="divide-y divide-line overflow-hidden rounded-uber border border-line bg-white">
              {visible.map((item, index) => (
                <li key={`${item.id}-${index}`} className="px-3 py-2 text-sm">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-medium text-ink">{item.id}</span>
                    <span className="text-ink">{humanizeDecision(item.decision)}</span>
                    <span className="text-xs text-muted">{humanizeSource(item.by)}</span>
                  </div>
                  {item.rationale ? <p className="mt-1 text-muted">{item.rationale}</p> : null}
                </li>
              ))}
            </ul>
          );
        }}
      </Disclosure>
    </Section>
  );
}
