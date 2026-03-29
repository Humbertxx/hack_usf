"use client";

import { Card } from "@/app/components/Card";
import { SectionHeader } from "@/app/components/SectionHeader";
import InsightCard, {
  type InsightMetricKey,
  type TrendRow,
} from "../components/InsightCard";
import { useEffect, useState } from "react";

export default function Home() {
  const [person, setPerson] = useState<"grandma" | "grandpa">("grandma");
  const [metric, setMetric] = useState<InsightMetricKey>("meals");
  const [trends, setTrends] = useState<TrendRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({
          person_id: person,
          days: "7",
        });
        const response = await fetch(`/api/insights-trends?${params.toString()}`, {
          method: "GET",
          cache: "no-store",
          signal: controller.signal,
        });
        const payload = (await response.json().catch(() => null)) as
          | { series?: TrendRow[]; detail?: string; error?: string }
          | null;

        if (!response.ok) {
          throw new Error(
            payload?.detail || payload?.error || "Failed to load insights trends",
          );
        }
        setTrends(Array.isArray(payload?.series) ? payload.series : []);
      } catch (err) {
        if (controller.signal.aborted) return;
        const message =
          err instanceof Error ? err.message : "Failed to load insights trends";
        setError(message);
        setTrends([]);
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    };
    void load();
    return () => controller.abort();
  }, [person]);

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
            onClick={() => setPerson("grandma")}
            className={`h-full flex-1 px-5 text-sm font-medium transition duration-200 ds-motion-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ${
              person === "grandma"
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "bg-[var(--surface)] text-neutral-600 hover:bg-sky-100/50"
            }`}
          >
            Grandma
          </button>
          <button
            type="button"
            onClick={() => setPerson("grandpa")}
            className={`h-full flex-1 px-5 text-sm font-medium transition duration-200 ds-motion-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ${
              person === "grandpa"
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "bg-[var(--surface)] text-neutral-600 hover:bg-sky-100/50"
            }`}
          >
            Grandpa
          </button>
        </Card>
      </div>

      <section
        className="space-y-4"
        aria-label={`${person === "grandma" ? "Grandma" : "Grandpa"} insights`}
      >
        <h2 className="text-section-label">
          {person === "grandma" ? "Grandma" : "Grandpa"}
        </h2>
        <InsightCard
          person={person}
          metric={metric}
          setMetric={setMetric}
          trends={trends}
          loading={loading}
          error={error}
        />
      </section>
    </div>
  );
}
