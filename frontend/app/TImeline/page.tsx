"use client";

import { Card } from "@/app/components/Card";
import { SectionHeader } from "@/app/components/SectionHeader";
import { isHackUsfDemoSession } from "@/lib/demo-session";
import { useEffect, useState } from "react";

export default function Home() {
  type TimelineRange = "today" | "yesterday" | "week";
  type TimelinePerson = "grandma" | "grandpa";
  interface TimelineItem {
    observed_at: string | null;
    time: string;
    title: string;
    summary: string;
    event_type: string;
  }

  const [range, setRange] = useState<TimelineRange>("today");
  const [person, setPerson] = useState<TimelinePerson>("grandma");
  const [items, setItems] = useState<TimelineItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isDemoMode, setIsDemoMode] = useState(false);

  useEffect(() => {
    setIsDemoMode(isHackUsfDemoSession());
  }, []);

  useEffect(() => {
    if (!isDemoMode) {
      setItems([]);
      setLoading(false);
      setError(null);
      return;
    }
    const controller = new AbortController();
    const load = async () => {
      setLoading(true);
      setError(null);
      try {
        const params = new URLSearchParams({ person_id: person, range });
        const response = await fetch(`/api/timeline?${params.toString()}`, {
          method: "GET",
          cache: "no-store",
          signal: controller.signal,
        });
        const payload = (await response.json().catch(() => null)) as
          | { items?: TimelineItem[]; detail?: string; error?: string }
          | null;
        if (!response.ok) {
          throw new Error(payload?.detail || payload?.error || "Failed to load timeline");
        }
        setItems(Array.isArray(payload?.items) ? payload.items : []);
      } catch (err) {
        if (controller.signal.aborted) return;
        setItems([]);
        setError(err instanceof Error ? err.message : "Failed to load timeline");
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    };
    void load();
    return () => controller.abort();
  }, [person, range, isDemoMode]);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-8 px-6 py-10">
      <SectionHeader
        eyebrow="Day view"
        title="Activity Timeline"
        description="Here's what's happening today."
      />

      <div className="flex flex-col gap-4 lg:flex-row lg:justify-between">
        <Card hover={false} padded={false} className="flex h-[52px] p-0">
          <button
            type="button"
            onClick={() => setRange("today")}
            className={`flex-1 rounded-l-2xl px-3 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ds-motion-hover ${
              range === "today"
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "hover:bg-sky-100/50"
            }`}
          >
            Today
          </button>
          <button
            type="button"
            onClick={() => setRange("yesterday")}
            className={`flex-1 px-3 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ds-motion-hover ${
              range === "yesterday"
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "hover:bg-sky-100/50"
            }`}
          >
            Yesterday
          </button>
          <button
            type="button"
            onClick={() => setRange("week")}
            className={`flex-1 rounded-r-2xl px-3 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ds-motion-hover ${
              range === "week"
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "hover:bg-sky-100/50"
            }`}
          >
            Last week
          </button>
        </Card>

        <Card hover={false} padded={false} className="flex h-[52px] p-0">
          <button
            type="button"
            onClick={() => setPerson("grandma")}
            className={`flex-1 rounded-l-2xl px-4 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ds-motion-hover ${
              person === "grandma"
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "hover:bg-sky-100/50"
            }`}
          >
            Grandma
          </button>
          <button
            type="button"
            onClick={() => setPerson("grandpa")}
            className={`flex-1 rounded-r-2xl px-4 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ds-motion-hover ${
              person === "grandpa"
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "hover:bg-sky-100/50"
            }`}
          >
            Grandpa
          </button>
        </Card>
      </div>

      {!isDemoMode ? (
        <Card hover={false} className="text-neutral-600">
          Timeline is unavailable outside demo mode. Open /demo to view mock data.
        </Card>
      ) : loading && items.length === 0 ? (
        <Card hover={false} className="text-neutral-600">
          Loading timeline...
        </Card>
      ) : error ? (
        <Card hover={false} className="text-red-600">
          {error}
        </Card>
      ) : items.length === 0 ? (
        <Card hover={false} className="text-neutral-600">
          No timeline events found for this person and range.
        </Card>
      ) : (
        <ul className="relative flex flex-col gap-4">
          {items.map((item, index) => (
            <li
              key={`${item.observed_at ?? "row"}-${index}`}
              className="flex gap-4"
            >
              <div className="flex flex-col items-center">
                <div
                  className="h-12 w-12 shrink-0 rounded-full bg-[var(--accent-strong)] ring-2 ring-white/50"
                  aria-hidden
                />
                {index !== items.length - 1 ? (
                  <div
                    className="w-px flex-1 min-h-[2.5rem] bg-[var(--accent-strong)]/70"
                    aria-hidden
                  />
                ) : null}
              </div>
              <Card
                hover
                className="animate-dash-in flex min-h-[4.75rem] flex-1 flex-col justify-center gap-1"
                style={{ animationDelay: `${index * 50}ms` }}
              >
                <div className="flex w-full flex-wrap items-start justify-between gap-2">
                  <h3 className="text-lg font-semibold text-neutral-900">
                    {item.title}
                  </h3>
                  <time
                    className="text-xs tabular-nums text-neutral-600"
                    dateTime={item.observed_at ?? undefined}
                  >
                    {item.time}
                  </time>
                </div>
                <p className="text-body-reading text-sm">{item.summary}</p>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
