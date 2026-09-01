"use client";

import { useState } from "react";

import { AccuracyPanel } from "@/components/AccuracyPanel";
import { MatchedItems } from "@/components/MatchedItems";
import { ReviewTimeline } from "@/components/ReviewTimeline";
import { RunHistory } from "@/components/RunHistory";
import { TaxResults } from "@/components/TaxResults";
import type { DashboardRun } from "@/lib/types";

const TABS = [
  { id: "accuracy", label: "Accuracy" },
  { id: "closed", label: "Closed items" },
  { id: "tax", label: "Tax" },
  { id: "activity", label: "Activity" },
  { id: "history", label: "History" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export function EvidenceTabs({ data }: { data: DashboardRun }) {
  const [tab, setTab] = useState<TabId>("accuracy");

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-medium text-slate-700">Can I trust it?</h2>
        <p className="text-xs text-slate-500">Accuracy, closed items, tax, activity, and prior runs of this dataset.</p>
      </div>
      <div className="flex flex-wrap gap-1 border-b border-slate-200">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            className={`px-3 py-1.5 text-sm ${
              tab === item.id
                ? "border-b-2 border-slate-900 font-medium text-slate-900"
                : "text-slate-500 hover:text-slate-800"
            }`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      {tab === "accuracy" ? <AccuracyPanel data={data} /> : null}
      {tab === "closed" ? <MatchedItems matches={data.matches ?? []} /> : null}
      {tab === "tax" ? <TaxResults data={data} /> : null}
      {tab === "activity" ? <ReviewTimeline items={data.investigations ?? []} /> : null}
      {tab === "history" ? <RunHistory store={data.store} /> : null}
    </section>
  );
}
