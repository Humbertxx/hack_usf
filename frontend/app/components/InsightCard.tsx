"use client";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

import { useState } from "react";
import { Card, CardButton } from "./Card";

export type TrendRow = {
  date: string;
  label: string;
  meals_per_day: number;
  falls_per_day: number;
  activity_level: number;
};

export type InsightMetricKey = "meals" | "falls" | "activity";

type InsightCardProps = {
  person: "grandma" | "grandpa";
  metric: InsightMetricKey;
  setMetric: (value: InsightMetricKey) => void;
  trends: TrendRow[];
  loading: boolean;
  error: string | null;
  dataUnavailable?: boolean;
  dataUnavailableMessage?: string;
  chatEnabled?: boolean;
  chatDisabledMessage?: string;
};

export default function InsightCard({
  person,
  setMetric,
  metric,
  trends,
  loading,
  error,
  dataUnavailable = false,
  dataUnavailableMessage = "Insights are unavailable.",
  chatEnabled = true,
  chatDisabledMessage = "Insights chat is currently unavailable.",
}: InsightCardProps) {
  const [message, setMessage] = useState("");
  const [receivedMessage, setReceivedMessage] = useState(
    "Ask me anything about your loved ones!",
  );
  const [chatBusy, setChatBusy] = useState(false);

  const totalMeals = trends.reduce((sum, row) => sum + row.meals_per_day, 0);
  const totalFalls = trends.reduce((sum, row) => sum + row.falls_per_day, 0);
  const avgMeals = trends.length ? totalMeals / trends.length : 0;
  const avgActivity = trends.length
    ? trends.reduce((sum, row) => sum + row.activity_level, 0) / trends.length
    : 0;

  const metricCards: Array<{
    key: InsightMetricKey;
    name: string;
    measurement: string;
    description: string;
  }> = [
    {
      key: "meals",
      name: "Meals/day",
      measurement: dataUnavailable ? "--" : `${avgMeals.toFixed(1)}/day`,
      description: dataUnavailable ? "Demo mode required" : `${totalMeals} meals across 7 days`,
    },
    {
      key: "falls",
      name: "Falls/day",
      measurement: dataUnavailable ? "--" : `${totalFalls}`,
      description: dataUnavailable ? "Demo mode required" : "Total fall alerts in this window",
    },
    {
      key: "activity",
      name: "Activity level",
      measurement: dataUnavailable ? "--" : `${Math.round(avgActivity)}/100`,
      description: dataUnavailable ? "Demo mode required" : "Daily active-pose score",
    },
  ];

  const chartData = trends.map((row) => ({
    label: row.label,
    value:
      metric === "meals"
        ? row.meals_per_day
        : metric === "falls"
          ? row.falls_per_day
          : row.activity_level,
  }));

  const chartStroke =
    metric === "meals" ? "#3b82f6" : metric === "falls" ? "#ef4444" : "#10b981";
  const personLabel = person === "grandma" ? "Grandma" : "Grandpa";

  return (
    <>
      <div className="flex w-full flex-wrap items-center justify-between gap-5">
        <div className="flex w-full flex-col items-center gap-3">
          <Card
            hover={false}
            className="flex min-h-[200px] w-full items-center justify-center rounded-2xl bg-white/90 text-xl text-neutral-600"
          >
            {receivedMessage}
          </Card>
          <div className="flex w-full items-center justify-between gap-3">
            <input
              className="h-10 w-[45%] rounded-xl border border-[var(--border-subtle)] bg-[var(--surface)] px-3 text-sm shadow-sm ring-1 ring-[var(--ring-subtle)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/40"
              placeholder="Type your message..."
              value={message}
              onChange={(e) => setMessage(e.target.value)}
            />
            <button
              type="button"
              disabled={chatBusy || !chatEnabled}
              onClick={async () => {
                const trimmed = message.trim();
                if (!trimmed) return;
                if (!chatEnabled) {
                  setReceivedMessage(chatDisabledMessage);
                  return;
                }
                setChatBusy(true);
                try {
                  const response = await fetch("/api/insights-chat", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ message: trimmed, person_id: person }),
                  });
                  const payload = (await response.json().catch(() => null)) as
                    | { reply?: string; detail?: string; error?: string }
                    | null;
                  if (!response.ok) {
                    throw new Error(
                      payload?.detail ||
                        payload?.error ||
                        "Failed to fetch insights chat response",
                    );
                  }
                  const reply = payload?.reply?.trim();
                  setReceivedMessage(
                    reply || `No reply returned for ${personLabel}. Try a new question.`,
                  );
                  setMessage("");
                } catch (err) {
                  const errMsg =
                    err instanceof Error ? err.message : "Failed to contact insights chat";
                  setReceivedMessage(`Error: ${errMsg}`);
                } finally {
                  setChatBusy(false);
                }
              }}
              className="h-10 w-[45%] rounded-xl border border-[var(--border-subtle)] bg-[var(--surface)] text-sm font-medium shadow-sm ring-1 ring-[var(--ring-subtle)] transition duration-200 hover:bg-[var(--surface-muted)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/40 ds-motion-hover"
            >
              {chatBusy ? "Sending..." : "Send"}
            </button>
          </div>
        </div>
        {metricCards.map((item) => (
          <CardButton
            key={item.key}
            className={`flex flex-col items-start justify-center gap-2 md:h-[110px] md:w-[210px] 2xl:h-[180px] 2xl:w-[320px] ${
              metric === item.key
                ? "bg-[var(--surface-muted)] ring-emerald-600/30"
                : ""
            } ${dataUnavailable ? "cursor-not-allowed opacity-70" : ""}`}
            onClick={() => {
              if (dataUnavailable) return;
              setMetric(item.key);
            }}
          >
            <p className="text-sm font-medium uppercase tracking-wide text-neutral-500">
              {item.name}
            </p>
            <p className="text-2xl font-semibold tabular-nums">
              {item.measurement}
            </p>
            <p className="text-base text-neutral-600">{item.description}</p>
          </CardButton>
        ))}
        <Card
          hover={false}
          className="h-[400px] min-h-[400px] w-full min-w-0 overflow-hidden p-3 md:p-4"
        >
          {dataUnavailable ? (
            <div className="flex h-full items-center justify-center text-neutral-500">
              {dataUnavailableMessage}
            </div>
          ) : loading && chartData.length === 0 ? (
            <div className="flex h-full items-center justify-center text-neutral-500">
              Loading weekly trends...
            </div>
          ) : error ? (
            <div className="flex h-full items-center justify-center text-red-600">
              {error}
            </div>
          ) : (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="label" />
                <YAxis domain={metric === "activity" ? [0, 100] : ["auto", "auto"]} />
                <Tooltip />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke={chartStroke}
                  strokeWidth={3}
                  dot={{ r: 3 }}
                  activeDot={{ r: 6 }}
                />
              </LineChart>
            </ResponsiveContainer>
          )}
        </Card>
      </div>
    </>
  );
}
