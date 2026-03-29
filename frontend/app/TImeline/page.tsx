"use client";

import { Card } from "@/app/components/Card";
import { SectionHeader } from "@/app/components/SectionHeader";
import { useEffect, useState } from "react";

export default function Home() {
  interface basicstatus {
    type: string;
    text: string;
    time: string;
  }

  const values: basicstatus[] = [
    { type: "Waking hours", text: "SLept well", time: "6:20am" },
    { type: "Coffee?", text: "Iced", time: "6:30am" },
    { type: "Brushin", text: "Teeth nice and clean", time: "6:40am" },
    { type: "Cruisin", text: "Granny has a nice car", time: "6:50am" },
  ];

  const [time, settime] = useState(0);
  const [grandma, setgrandma] = useState(true);
  const [grandpa, setgrandpa] = useState(false);
  const [line, setline] = useState(0);

  useEffect(() => {
    setline(values.length - 1);
  }, [values]);

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
            onClick={time === 0 ? () => settime(-1) : () => settime(0)}
            className={`flex-1 rounded-l-2xl px-3 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ds-motion-hover ${
              time === 0
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "hover:bg-sky-100/50"
            }`}
          >
            Today
          </button>
          <button
            type="button"
            onClick={time === 1 ? () => settime(-1) : () => settime(1)}
            className={`flex-1 px-3 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ds-motion-hover ${
              time === 1
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "hover:bg-sky-100/50"
            }`}
          >
            Yesterday
          </button>
          <button
            type="button"
            onClick={time === 2 ? () => settime(-1) : () => settime(2)}
            className={`flex-1 rounded-r-2xl px-3 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ds-motion-hover ${
              time === 2
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
            onClick={() => setgrandma(!grandma)}
            className={`flex-1 rounded-l-2xl px-4 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ds-motion-hover ${
              grandma
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "hover:bg-sky-100/50"
            }`}
          >
            Grandma
          </button>
          <button
            type="button"
            onClick={() => setgrandpa(!grandpa)}
            className={`flex-1 rounded-r-2xl px-4 text-sm font-medium transition duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-emerald-600/40 ds-motion-hover ${
              grandpa
                ? "bg-[var(--surface-muted)] text-neutral-900"
                : "hover:bg-sky-100/50"
            }`}
          >
            Grandpa
          </button>
        </Card>
      </div>

      <ul className="relative flex flex-col gap-4">
        {values.map((item, index) => (
          <li key={item.time} className="flex gap-4">
            <div className="flex flex-col items-center">
              <div
                className="h-12 w-12 shrink-0 rounded-full bg-[var(--accent-strong)] ring-2 ring-white/50"
                aria-hidden
              />
              {index !== line ? (
                <div
                  className="w-px flex-1 min-h-[2.5rem] bg-[var(--accent-strong)]/70"
                  aria-hidden
                />
              ) : null}
            </div>
            <Card
              hover
              className={`animate-dash-in flex min-h-[4.75rem] flex-1 flex-col justify-center gap-1`}
              style={{ animationDelay: `${index * 50}ms` }}
            >
              <div className="flex w-full flex-wrap items-start justify-between gap-2">
                <h3 className="text-lg font-semibold text-neutral-900">
                  {item.type}
                </h3>
                <time
                  className="text-xs tabular-nums text-neutral-600"
                  dateTime={item.time}
                >
                  {item.time}
                </time>
              </div>
              <p className="text-body-reading text-sm">{item.text}</p>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
}
