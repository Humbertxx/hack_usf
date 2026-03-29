"use client";

import {
  DASHBOARD_FULL_STACK_FIRED_KEY,
  ENROLLMENT_QUERY,
  ENROLLMENT_VALUE,
} from "@/lib/enrollment-flags";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

const LIVE_EVENTS_TZ = "America/New_York";
const POLL_MS = 120_000;

type LiveEventItem = {
  id: string | null;
  event_type: string | null;
  headline: string | null;
  summary: string | null;
  meal_kind: string | null;
  observed_at: string | null;
  display_name: string | null;
  frame_thumb_base64: string | null;
};

type LiveEventsPayload = {
  timezone?: string;
  events: LiveEventItem[];
  detail?: string;
  error?: string;
};

function formatEventTimes(iso: string | null, tz: string) {
  if (!iso) {
    return { absolute: "—", relative: "" };
  }
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) {
    return { absolute: "—", relative: "" };
  }
  const absolute = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour: "numeric",
    minute: "2-digit",
  }).format(d);
  const diffMs = Date.now() - d.getTime();
  const mins = Math.round(diffMs / 60_000);
  let relative: string;
  if (mins <= 0) relative = "just now";
  else if (mins < 60) relative = `${mins} min ago`;
  else if (mins < 1440) relative = `${Math.floor(mins / 60)} hr ago`;
  else relative = `${Math.floor(mins / 1440)} days ago`;
  return { absolute, relative };
}

/** Persist across reload if the 6s timer was scheduled but the tab navigated away / refreshed. */
const FULL_STACK_SCHEDULED_KEY = "hack_usf_dashboard_full_stack_scheduled";

function DashboardInner() {
  const searchParams = useSearchParams();
  const router = useRouter();

  useEffect(() => {
    if (searchParams.get(ENROLLMENT_QUERY) !== ENROLLMENT_VALUE) return;

    if (sessionStorage.getItem(DASHBOARD_FULL_STACK_FIRED_KEY) === "1") {
      router.replace("/dashboard");
      return;
    }

    // Recovery: timer was lost (e.g. refresh) but enrollment landing was not yet completed.
    if (sessionStorage.getItem(FULL_STACK_SCHEDULED_KEY) === "1") {
      sessionStorage.removeItem(FULL_STACK_SCHEDULED_KEY);
      void fetch("/api/start-full-stack", { method: "POST" }).finally(() => {
        sessionStorage.setItem(DASHBOARD_FULL_STACK_FIRED_KEY, "1");
        router.replace("/dashboard");
      });
      return;
    }

    sessionStorage.setItem(FULL_STACK_SCHEDULED_KEY, "1");
    const timer = window.setTimeout(() => {
      void fetch("/api/start-full-stack", { method: "POST" }).finally(() => {
        sessionStorage.setItem(DASHBOARD_FULL_STACK_FIRED_KEY, "1");
        sessionStorage.removeItem(FULL_STACK_SCHEDULED_KEY);
        router.replace("/dashboard");
      });
    }, 6000);

    return () => {
      window.clearTimeout(timer);
      sessionStorage.removeItem(FULL_STACK_SCHEDULED_KEY);
    };
  }, [searchParams, router]);
  interface basicstatus {
    type: string;
    val: string;
  }

  const [name, setname] = useState("Grandma");
  const [liveEvents, setLiveEvents] = useState<LiveEventItem[]>([]);
  const [eventsTz, setEventsTz] = useState(LIVE_EVENTS_TZ);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null);

  const values: basicstatus[] = [
    { type: "Active Hours", val: "8.5" },
    { type: "Sleep Quality", val: "Good" },
    { type: "Exercise", val: "1" },
    { type: "Meals", val: "3" },
  ];

  const fetchLiveEvents = useCallback(async () => {
    try {
      const r = await fetch("/api/live-events?minutes=30&limit=50", {
        cache: "no-store",
      });
      const data: LiveEventsPayload = await r.json();
      if (!r.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : data.error ?? `HTTP ${r.status}`;
        setEventsError(msg);
        return;
      }
      setEventsError(null);
      setLiveEvents(Array.isArray(data.events) ? data.events : []);
      if (typeof data.timezone === "string" && data.timezone) {
        setEventsTz(data.timezone);
      }
      setLastSyncedAt(new Date());
    } catch {
      setEventsError("Could not load live events");
    } finally {
      setEventsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchLiveEvents();
    const id = window.setInterval(() => void fetchLiveEvents(), POLL_MS);
    return () => window.clearInterval(id);
  }, [fetchLiveEvents]);

  const syncLabel = lastSyncedAt
    ? new Intl.DateTimeFormat("en-US", {
        timeZone: eventsTz,
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
      }).format(lastSyncedAt)
    : null;

  return (
    <>
      <div className="p-10 w-full h-full flex flex-col gap-10 items-center justify-start">
        <div className="flex justify-between w-[90%] md:w-[80%]">
          <div className="flex flex-col gap-3">
            <p className="font-bold text-3xl">Hello!</p>
            <p className="font-thin text-gray-600 text-sm">
              Here is whats happening with {name} today!
            </p>
          </div>
          <div
            className="flex items-center gap-2 rounded-full border border-white/40 bg-white/60 px-3 py-1.5 text-sm text-neutral-800 shadow-sm backdrop-blur-sm"
            title={
              syncLabel
                ? `Last synced ${syncLabel} (${eventsTz})`
                : "Waiting for first sync"
            }
          >
            <span
              className="inline-block h-2 w-2 shrink-0 rounded-full bg-emerald-500"
              aria-hidden
            />
            <span className="font-medium">Monitoring</span>
            {syncLabel ? (
              <span className="text-neutral-500">· {syncLabel}</span>
            ) : null}
          </div>
        </div>
        <div className="flex items-center justify-center gap-5 md:gap-10 w-[90%] md:w-[80%]">
          {values.map((item, index) => (
            <div
              key={index}
              className="shadow hover:shadow-xl transition duration-100 ease-in flex flex-col items-center justify-center bg-sky-50 w-[200px] h-[100px] lg:w-[500px] rounded-2xl"
            >
              <p className="font-thin">{item.type}</p>
              <p className="font-bold text-xl">{item.val}</p>
            </div>
          ))}
        </div>
        <div className="flex flex-col gap-5 flex-wrap items-center justify-between w-[90%] md:w-[80%]">
          <div className="flex w-full flex-wrap items-end justify-between gap-2">
            <p className="font-bold text-3xl self-start">Live Updates</p>
            <p className="text-xs text-neutral-600">
              Refreshes every 2 min · {eventsTz.replace("_", " ")}
            </p>
          </div>
          {eventsError ? (
            <div className="w-full rounded-2xl border border-amber-200/80 bg-amber-50/90 px-4 py-3 text-sm text-amber-950">
              {eventsError}
            </div>
          ) : null}
          {eventsLoading ? (
            <div className="flex w-full flex-col gap-3">
              {[0, 1, 2].map((i) => (
                <div
                  key={i}
                  className="h-24 w-full animate-pulse rounded-2xl bg-sky-50/80 ring-1 ring-black/5"
                />
              ))}
            </div>
          ) : liveEvents.length === 0 && !eventsError ? (
            <p className="w-full rounded-2xl border border-white/40 bg-sky-50/80 px-4 py-6 text-center text-sm text-neutral-600 shadow-sm ring-1 ring-black/5">
              No recent events in the last 30 minutes. Events appear after the
              Snowflake task processes eating and fall alerts.
            </p>
          ) : (
            liveEvents.map((ev) => {
              const title =
                ev.headline?.trim() ||
                ev.event_type?.replace(/_/g, " ") ||
                "Update";
              const { absolute, relative } = formatEventTimes(
                ev.observed_at,
                eventsTz,
              );
              const timeLine =
                relative && absolute
                  ? `${absolute} · ${relative}`
                  : absolute;
              const thumb = ev.frame_thumb_base64?.trim();
              return (
                <article
                  key={ev.id ?? `${ev.observed_at}-${title}`}
                  className="flex w-full flex-col gap-3 rounded-2xl border border-white/40 bg-sky-50 p-4 shadow-sm ring-1 ring-black/5 transition hover:shadow-md"
                >
                  <div className="flex w-full flex-wrap items-start justify-between gap-2">
                    <p className="font-bold text-xl text-neutral-900">{title}</p>
                    <p className="text-xs text-neutral-600 whitespace-nowrap">
                      {timeLine}
                    </p>
                  </div>
                  {ev.display_name ? (
                    <p className="text-xs font-medium uppercase tracking-wide text-neutral-500">
                      {ev.display_name}
                      {ev.meal_kind
                        ? ` · ${ev.meal_kind.replace(/_/g, " ")}`
                        : ""}
                    </p>
                  ) : null}
                  {ev.summary ? (
                    <p className="text-sm leading-relaxed text-neutral-800">
                      {ev.summary}
                    </p>
                  ) : null}
                  {thumb ? (
                    <img
                      src={`data:image/jpeg;base64,${thumb}`}
                      alt=""
                      loading="lazy"
                      className="max-h-48 w-full max-w-md rounded-xl object-cover ring-1 ring-black/10"
                    />
                  ) : null}
                </article>
              );
            })
          )}
        </div>
      </div>
    </>
  );
}

export default function DashboardPage() {
  return (
    <Suspense
      fallback={
        <div className="p-10 w-full flex items-center justify-center text-gray-600">
          Loading dashboard…
        </div>
      }
    >
      <DashboardInner />
    </Suspense>
  );
}
