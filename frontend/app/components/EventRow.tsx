"use client";

import { Card } from "./Card";

export type EventRowProps = {
  title: string;
  timeLine: string;
  subtitle?: string | null;
  summary?: string | null;
  /** `data:image/jpeg;base64,...` or plain base64 (prefix added if missing) */
  imageSrc?: string | null;
  /** For staggered entrance; omit for no animation class */
  animationIndex?: number;
};

function thumbDataUrl(raw: string): string {
  const t = raw.trim();
  if (t.startsWith("data:")) return t;
  return `data:image/jpeg;base64,${t}`;
}

export function EventRow({
  title,
  timeLine,
  subtitle,
  summary,
  imageSrc,
  animationIndex = 0,
}: EventRowProps) {
  const thumb = imageSrc?.trim();
  const delayMs = animationIndex * 55;

  return (
    <Card
      hover
      className="animate-dash-in flex w-full flex-col gap-3"
      style={{ animationDelay: `${delayMs}ms` }}
    >
      <div className="flex w-full flex-wrap items-start justify-between gap-2">
        <h3 className="text-xl font-semibold tracking-tight text-neutral-900">
          {title}
        </h3>
        <p className="whitespace-nowrap text-xs tabular-nums text-neutral-600">
          {timeLine}
        </p>
      </div>
      {subtitle ? (
        <p className="text-xs font-medium uppercase tracking-wide text-neutral-500">
          {subtitle}
        </p>
      ) : null}
      {summary ? (
        <p className="text-body-reading text-sm leading-relaxed">{summary}</p>
      ) : null}
      {thumb ? (
        <img
          src={thumbDataUrl(thumb)}
          alt=""
          loading="lazy"
          className="aspect-[4/3] max-h-48 w-full max-w-md rounded-xl object-cover ring-1 ring-black/10"
        />
      ) : null}
    </Card>
  );
}
