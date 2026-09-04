"use client";

import { useState } from "react";

import { AccuracyPanel } from "@/components/AccuracyPanel";
import { MatchedItems } from "@/components/MatchedItems";
import { ReviewTimeline } from "@/components/ReviewTimeline";
import { RunHistory } from "@/components/RunHistory";
import { TaxResults } from "@/components/TaxResults";
import type { DashboardRun } from "@/lib/types";

const TABS = [
  { id: "accuracy", label: "Quality" },
  { id: "closed", label: "Matched items" },
  { id: "tax", label: "Tax" },
  { id: "activity", label: "What we did" },
  { id: "history", label: "Earlier runs" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function EvidenceTabs({ data }: { data: DashboardRun }) {
  const [tab, setTab] = useState<TabId>("accuracy");

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-ink">Look closer</h2>
        <p className="mt-0.5 text-sm text-muted">Quality scores, matched items, tax, activity, and earlier runs of this file.</p>
      </div>
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Review details">
        {TABS.map((item) => {
          const selected = tab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={selected}
              className={`rounded-full px-3 py-1.5 text-sm ${
                selected ? "bg-black text-white" : "bg-white text-ink ring-1 ring-line hover:bg-wash"
              }`}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {tab === "accuracy" ? <AccuracyPanel data={data} /> : null}
      {tab === "closed" ? <MatchedItems matches={data.matches ?? []} /> : null}
      {tab === "tax" ? <TaxResults data={data} /> : null}
      {tab === "activity" ? <ReviewTimeline items={data.investigations ?? []} /> : null}
      {tab === "history" ? <RunHistory store={data.store} /> : null}
    </section>
  );
}
