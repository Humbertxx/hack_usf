"use client";

import { Card } from "@/app/components/Card";
import { SectionHeader } from "@/app/components/SectionHeader";
import InsightCard from "../components/InsightCard";
import { useState } from "react";

export default function Home() {
  const [grandma, setGrandma] = useState(true);
  const [grandpa, setGrandpa] = useState(false);
  const [grandmametric, setGrandmametric] = useState(0);
  const [grandpametric, setGrandpametric] = useState(0);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-8 px-6 py-10">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
        <SectionHeader
          eyebrow="Analytics"
          title="Health Insights"
          description="AI-powered analysis of weekly patterns and trends."
        />
        <Card
          hover={false}
          padded={false}
          className="inline-flex h-[52px] shrink-0 overflow-hidden p-0 ring-1 ring-[var(--ring-subtle)]"
        >
          <button
            type="button"
            onClick={() => setGrandma(!grandma)}
            className={`h-full flex-1 px-5 text-sm font-medium transition duration-200 ds-motion-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ${
              grandma
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "bg-[var(--surface)] text-neutral-600 hover:bg-sky-100/50"
            }`}
          >
            Grandma
          </button>
          <button
            type="button"
            onClick={() => setGrandpa(!grandpa)}
            className={`h-full flex-1 px-5 text-sm font-medium transition duration-200 ds-motion-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ${
              grandpa
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "bg-[var(--surface)] text-neutral-600 hover:bg-sky-100/50"
            }`}
          >
            Grandpa
          </button>
        </Card>
      </div>

      {grandma ? (
        <section className="space-y-4" aria-label="Grandma insights">
          <h2 className="text-section-label">Grandma</h2>
          <InsightCard
            person="grandma"
            metric={grandmametric}
            setmetric={setGrandmametric}
          />
        </section>
      ) : null}
      {grandpa ? (
        <section className="space-y-4" aria-label="Grandpa insights">
          <h2 className="text-section-label">Grandpa</h2>
          <div className="flex flex-wrap items-center justify-between gap-5">
            <InsightCard
              person="grandpa"
              metric={grandpametric}
              setmetric={setGrandpametric}
            />
          </div>
        </section>
      ) : null}
    </div>
  );
}
