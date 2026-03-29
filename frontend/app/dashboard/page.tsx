"use client";

import { Card } from "@/app/components/Card";
import { EventRow } from "@/app/components/EventRow";
import { SectionHeader } from "@/app/components/SectionHeader";
import { StatusBadge } from "@/app/components/StatusBadge";
import {
  isHackUsfDemoSession,
} from "@/lib/demo-session";
import {
  DASHBOARD_FULL_STACK_FIRED_KEY,
  ENROLLMENT_QUERY,
  ENROLLMENT_VALUE,
} from "@/lib/enrollment-flags";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

const LIVE_EVENTS_TZ = "America/New_York";
const LIVE_EVENTS_POLL_MS = 3_000;
/** Demo mode: seven-day lookback so seeded LIVE_EVENTS remain visible. */
const DEMO_LIVE_EVENTS_LOOKBACK_MINUTES = 10_080;
const DEMO_LIVE_EVENTS_POLL_MIN_MS = 2_000;
const DEMO_LIVE_EVENTS_POLL_MAX_MS = 5_000;
const PRIMARY_STATE_POLL_MS = 1_000;

function demoLiveEventsPollDelayMs(): number {
  return (
    DEMO_LIVE_EVENTS_POLL_MIN_MS +
    Math.floor(
      Math.random() *
        (DEMO_LIVE_EVENTS_POLL_MAX_MS - DEMO_LIVE_EVENTS_POLL_MIN_MS + 1),
    )
  );
}

type LiveEventItem = {
  id: string | null;
  dedupe_key?: string | null;
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

type PrimaryStatePayload = {
  present?: boolean;
  timezone?: string;
  pose?: string | null;
  display_name?: string | null;
  observed_at?: string | null;
  session_id?: string | null;
  activity?: string | null;
  fallen_attention?: boolean;
  detail?: string;
  error?: string;
};

function collapseConsecutiveDedupeKeys(events: LiveEventItem[]): LiveEventItem[] {
  const out: LiveEventItem[] = [];
  for (const ev of events) {
    const key = ev.dedupe_key ?? ev.event_type ?? ev.id ?? "";
    const last = out[out.length - 1];
    const lastKey = last
      ? (last.dedupe_key ?? last.event_type ?? last.id ?? "")
      : null;
    if (lastKey !== null && key !== "" && key === lastKey) continue;
    out.push(ev);
  }
  return out;
}

function postureHeadline(
  pose: string | null | undefined,
  fallenAttention: boolean | undefined,
) {
  if (fallenAttention) return "Fallen / on floor";
  switch (pose) {
    case "sitting":
      return "Sitting";
    case "standing":
      return "Standing";
    case "walking":
      return "Walking";
    case "lying":
      return "Lying down";
    default:
      return "Unknown";
  }
}

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

  const [name] = useState("Grandma");
  const [liveEvents, setLiveEvents] = useState<LiveEventItem[]>([]);
  const [eventsTz, setEventsTz] = useState(LIVE_EVENTS_TZ);
  const [eventsLoading, setEventsLoading] = useState(true);
  const [eventsError, setEventsError] = useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = useState<Date | null>(null);
  const [primaryState, setPrimaryState] = useState<PrimaryStatePayload | null>(
    null,
  );
  const [primaryError, setPrimaryError] = useState<string | null>(null);

  const values: basicstatus[] = [
    { type: "Active Hours", val: "8.5" },
    { type: "Sleep Quality", val: "Good" },
    { type: "Exercise", val: "0" },
    { type: "Meals", val: "0" },
  ];

  const fetchLiveEvents = useCallback(async () => {
    try {
      const minutes = isHackUsfDemoSession()
        ? DEMO_LIVE_EVENTS_LOOKBACK_MINUTES
        : 30;
      const r = await fetch(`/api/live-events?minutes=${minutes}&limit=50`, {
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

  const fetchPrimaryState = useCallback(async () => {
    try {
      const r = await fetch("/api/primary-state", { cache: "no-store" });
      const data: PrimaryStatePayload = await r.json();
      if (!r.ok) {
        const msg =
          typeof data.detail === "string"
            ? data.detail
            : data.error ?? `HTTP ${r.status}`;
        setPrimaryError(msg);
        return;
      }
      setPrimaryError(null);
      setPrimaryState(data);
    } catch {
      setPrimaryError("Could not load current posture");
    }
  }, []);

  useEffect(() => {
    void fetchLiveEvents();

    if (!isHackUsfDemoSession()) {
      const id = window.setInterval(
        () => void fetchLiveEvents(),
        LIVE_EVENTS_POLL_MS,
      );
      return () => window.clearInterval(id);
    }

    let timeoutId = 0;
    const schedule = () => {
      timeoutId = window.setTimeout(() => {
        void fetchLiveEvents().finally(schedule);
      }, demoLiveEventsPollDelayMs());
    };
    schedule();
    return () => window.clearTimeout(timeoutId);
  }, [fetchLiveEvents]);

  useEffect(() => {
    void fetchPrimaryState();
    const id = window.setInterval(
      () => void fetchPrimaryState(),
      PRIMARY_STATE_POLL_MS,
    );
    return () => window.clearInterval(id);
  }, [fetchPrimaryState]);

  const syncLabel = lastSyncedAt
    ? new Intl.DateTimeFormat("en-US", {
        timeZone: eventsTz,
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
      }).format(lastSyncedAt)
    : null;

  const demoMode = isHackUsfDemoSession();

  return (
    <div className="mx-auto w-full max-w-5xl space-y-8 px-6 py-10">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <SectionHeader
          eyebrow="Today"
          title="Hello!"
          description={`Here's what's happening with ${name} today.`}
        />
        <StatusBadge
          label="Monitoring"
          detail={syncLabel}
          title={
            syncLabel
              ? `Last synced ${syncLabel} (${eventsTz})`
              : "Waiting for first sync"
          }
          className="self-start sm:mt-8"
        />
      </div>

      <section aria-labelledby="metrics-heading" className="space-y-4">
        <h2 id="metrics-heading" className="text-section-label">
          At a glance
        </h2>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {values.map((item) => (
            <Card
              key={item.type}
              className="flex min-h-[100px] flex-col items-center justify-center text-center"
            >
              <p className="text-section-label text-[0.65rem] leading-tight">
                {item.type}
              </p>
              <p className="mt-2 text-xl font-semibold tabular-nums text-neutral-900">
                {item.val}
              </p>
            </Card>
          ))}
        </div>
      </section>

      <section aria-labelledby="presence-heading" className="space-y-4">
        <SectionHeader
          id="presence-heading"
          title="Right now"
          description={`Updates every 1 sec · ${eventsTz.replace("_", " ")}`}
        />
        {primaryError ? (
          <Card
            hover={false}
            className="border-amber-200/90 bg-[var(--warning-bg)] text-[var(--warning-text)] ring-amber-200/50"
          >
            <p className="text-sm leading-relaxed">{primaryError}</p>
          </Card>
        ) : (
          <Card
            hover={false}
            className={`flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between ${
              primaryState?.fallen_attention
                ? "border-red-200/90 bg-red-50/80 ring-red-200/60"
                : ""
            }`}
          >
            <div>
              <p className="text-section-label text-[0.65rem] uppercase tracking-wide text-neutral-500">
                Primary person
              </p>
              <p className="mt-1 text-2xl font-semibold tracking-tight text-neutral-900">
                {postureHeadline(
                  primaryState?.pose,
                  primaryState?.fallen_attention,
                )}
              </p>
              {primaryState?.display_name ? (
                <p className="mt-1 text-sm text-neutral-600">
                  {primaryState.display_name}
                  {primaryState.activity &&
                  primaryState.activity !== "idle" &&
                  primaryState.activity !== "unknown"
                    ? ` · ${primaryState.activity.replace(/_/g, " ")}`
                    : ""}
                </p>
              ) : null}
            </div>
            {!primaryState?.present ? (
              <p className="text-sm text-neutral-500">
                Waiting for the first saved frame from the CV service…
              </p>
            ) : null}
          </Card>
        )}
      </section>

      <section aria-labelledby="live-heading" className="space-y-4">
        <SectionHeader
          id="live-heading"
          title="Live Updates"
          description={
            demoMode
              ? `Transitions & alerts · ~2–5 sec (demo) · ${eventsTz.replace("_", " ")}`
              : `Transitions & alerts · every 3 sec · ${eventsTz.replace("_", " ")}`
          }
        />

        {eventsError ? (
          <Card
            hover={false}
            className="border-amber-200/90 bg-[var(--warning-bg)] text-[var(--warning-text)] ring-amber-200/50"
          >
            <p className="text-sm leading-relaxed">{eventsError}</p>
          </Card>
        ) : null}

        {eventsLoading ? (
          <div className="flex flex-col gap-3">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-24 w-full animate-pulse rounded-2xl bg-[var(--surface)] ring-1 ring-[var(--ring-subtle)]"
              />
            ))}
          </div>
        ) : liveEvents.length === 0 && !eventsError ? (
          <Card hover={false} className="text-center">
            <p className="text-sm leading-relaxed text-neutral-600">
              No transitions yet. Eating, drinking water, and fall events from the
              CV service will appear here.
            </p>
          </Card>
        ) : (
          <div className="stagger-children flex flex-col gap-4">
            {collapseConsecutiveDedupeKeys(liveEvents).map((ev, index) => {
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
              const subtitle =
                ev.display_name != null && String(ev.display_name).trim()
                  ? `${ev.display_name}${ev.meal_kind ? ` · ${ev.meal_kind.replace(/_/g, " ")}` : ""}`
                  : ev.meal_kind
                    ? ev.meal_kind.replace(/_/g, " ")
                    : undefined;
              return (
                <EventRow
                  key={ev.id ?? `${ev.observed_at}-${title}-${index}`}
                  title={title}
                  timeLine={timeLine}
                  subtitle={subtitle}
                  summary={ev.summary}
                  imageSrc={ev.frame_thumb_base64}
                  animationIndex={index}
                />
              );
            })}
          </div>
        )}
      </section>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <Suspense
      fallback={
        <div className="text-body-reading flex min-h-[40vh] items-center justify-center px-6 text-neutral-600">
          Loading dashboard…
        </div>
      }
    >
      <DashboardInner />
    </Suspense>
  );
}
