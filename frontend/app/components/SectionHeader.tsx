"use client";

import type { ReactNode } from "react";

type SectionHeaderProps = {
  /** Small uppercase label above the title */
  eyebrow?: string;
  title: string;
  description?: string;
  aside?: ReactNode;
  className?: string;
  id?: string;
};

export function SectionHeader({
  eyebrow,
  title,
  description,
  aside,
  className = "",
  id,
}: SectionHeaderProps) {
  return (
    <header
      id={id}
      className={`flex w-full flex-wrap items-end justify-between gap-3 ${className}`}
    >
      <div className="min-w-0 space-y-1">
        {eyebrow ? <p className="text-section-label">{eyebrow}</p> : null}
        <h2 className="text-page-title">{title}</h2>
        {description ? (
          <p className="text-sm leading-relaxed text-neutral-600">{description}</p>
        ) : null}
      </div>
      {aside ? <div className="shrink-0">{aside}</div> : null}
    </header>
  );
}
