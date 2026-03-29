"use client";

import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from "react";

function cardClassName(
  padded: boolean,
  hover: boolean,
  extra: string,
): string {
  const base =
    "rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface)] shadow-sm ring-1 ring-[var(--ring-subtle)] " +
    "transition-[transform,box-shadow,border-color] duration-300 ease-out ds-motion-hover";
  const h = hover
    ? "hover:-translate-y-0.5 hover:shadow-md hover:ring-black/[0.08]"
    : "";
  const pad = padded ? "p-4 md:p-5" : "";
  return [base, h, pad, extra].filter(Boolean).join(" ");
}

type CardProps = {
  children: ReactNode;
  className?: string;
  padded?: boolean;
  hover?: boolean;
} & HTMLAttributes<HTMLDivElement>;

export function Card({
  children,
  className = "",
  padded = true,
  hover = true,
  ...rest
}: CardProps) {
  return (
    <div
      className={cardClassName(padded, hover, className)}
      {...rest}
    >
      {children}
    </div>
  );
}

type CardButtonProps = {
  children: ReactNode;
  className?: string;
  padded?: boolean;
  hover?: boolean;
} & ButtonHTMLAttributes<HTMLButtonElement>;

export function CardButton({
  children,
  className = "",
  padded = true,
  hover = true,
  ...rest
}: CardButtonProps) {
  return (
    <button
      type="button"
      className={`${cardClassName(
        padded,
        hover,
        className,
      )} w-full cursor-pointer text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/40`}
      {...rest}
    >
      {children}
    </button>
  );
}
