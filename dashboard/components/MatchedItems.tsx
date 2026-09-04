"use client";

import { useState } from "react";

import { humanizeTier } from "@/lib/format";
import type { DashboardMatch } from "@/lib/types";

import { Disclosure } from "./ui/Disclosure";
import { Panel } from "./ui/Panel";
import { Section } from "./ui/Section";

const PREVIEW = 8;

export function MatchedItems({ matches }: { matches: DashboardMatch[] }) {
  const [open, setOpen] = useState(false);

  return (
    <Section title="Matched items" subtitle="Payments that already lined up with a bank credit.">
      {matches.length === 0 ? (
        <Panel className="p-4 text-sm text-muted">Nothing closed in this review.</Panel>
      ) : (
        <>
          <button
            type="button"
            className="text-sm font-medium text-ink underline-offset-2 hover:underline"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide matched items" : `Show ${matches.length} matched items`}
          </button>
          {open ? (
            <Disclosure preview={PREVIEW} total={matches.length}>
              {(expanded) => (
                <ul className="divide-y divide-line overflow-hidden rounded-uber border border-line bg-white">
                  {(expanded ? matches : matches.slice(0, PREVIEW)).map((item) => (
                    <li key={item.id} className="px-3 py-2 text-sm">
                      <div className="flex flex-wrap items-baseline gap-2">
                        <span className="font-medium text-ink">{item.id}</span>
                        <span className="text-muted">{humanizeTier(item.tier)}</span>
                      </div>
                      {item.reason ? <p className="mt-1 text-ink">{item.reason}</p> : null}
                      {item.refs.length ? (
                        <p className="mt-0.5 text-xs text-muted">{item.refs.join(", ")}</p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </Disclosure>
          ) : null}
        </>
      )}
    </Section>
  );
}
