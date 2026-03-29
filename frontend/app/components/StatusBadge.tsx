"use client";

import type { HTMLAttributes, ReactNode } from "react";

type StatusBadgeProps = {
  label: string;
  /** Shown after a middle dot when set */
  detail?: ReactNode;
  /** Pulsing dot color; defaults to emerald */
  tone?: "emerald" | "green";
} & HTMLAttributes<HTMLDivElement>;

export function StatusBadge({
  label,
  detail,
  tone = "emerald",
  className = "",
  ...rest
}: StatusBadgeProps) {
  const dot =
    tone === "green" ? "bg-[var(--accent-strong)]" : "bg-[var(--accent)]";
  return (
    <div
      role="status"
      className={`flex items-center gap-2 rounded-full border border-[var(--border-subtle)] bg-[var(--surface-elevated)] px-3 py-1.5 text-sm text-neutral-800 shadow-sm backdrop-blur-sm ring-1 ring-[var(--ring-subtle)] ds-motion-hover ${className}`}
      {...rest}
    >
      <span
        className={`inline-block h-2 w-2 shrink-0 rounded-full ${dot}`}
        aria-hidden
      />
      <span className="font-medium">{label}</span>
      {detail ? (
        <span className="text-neutral-500 tabular-nums">· {detail}</span>
      ) : null}
    </div>
  );
}
