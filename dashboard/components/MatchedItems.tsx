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
    <Section title="Closed items" subtitle="Payments matched to bank credits, and how they closed.">
      {matches.length === 0 ? (
        <Panel className="p-4 text-sm text-slate-500">No items closed in this review.</Panel>
      ) : (
        <>
          <button
            type="button"
            className="text-sm text-slate-700 underline-offset-2 hover:underline"
            onClick={() => setOpen((v) => !v)}
          >
            {open ? "Hide closed items" : `Show ${matches.length} closed items`}
          </button>
          {open ? (
            <Disclosure preview={PREVIEW} total={matches.length}>
              {(expanded) => (
                <ul className="divide-y divide-slate-100 overflow-hidden rounded-lg border border-slate-200 bg-white">
                  {(expanded ? matches : matches.slice(0, PREVIEW)).map((item) => (
                    <li key={item.id} className="px-3 py-2 text-sm">
                      <div className="flex flex-wrap items-baseline gap-2">
                        <span className="font-medium text-slate-800">{item.id}</span>
                        <span className="text-slate-700">{humanizeTier(item.tier)}</span>
                      </div>
                      {item.reason ? <p className="mt-1 text-slate-600">{item.reason}</p> : null}
                      {item.refs.length ? (
                        <p className="mt-0.5 text-xs text-slate-500">{item.refs.join(", ")}</p>
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
