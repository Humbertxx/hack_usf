"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useOldPeopleContext } from "../OldPeopleContext";

const navLinkBase =
  "rounded-xl px-4 py-2 text-sm font-medium text-neutral-800 transition duration-200 ease-out ds-motion-hover " +
  "border border-[var(--border-subtle)] bg-[var(--surface)] shadow-sm ring-1 ring-[var(--ring-subtle)] " +
  "hover:bg-[var(--surface-muted)] hover:shadow-md focus-visible:outline-none focus-visible:ring-2 " +
  "focus-visible:ring-emerald-600/40";

export default function NavBar() {
  const { Navbar } = useOldPeopleContext();
  const pathname = usePathname();

  if (!Navbar) return null;

  const items = [
    { href: "/dashboard", label: "Home" },
    { href: "/TImeline", label: "Timeline" },
    { href: "/Insights", label: "Insights" },
  ];

  return (
    <nav
      className="flex w-full items-center justify-center border-b border-[var(--border-subtle)] bg-[var(--surface-elevated)] px-4 py-4 shadow-sm backdrop-blur-md md:justify-between md:px-10"
      aria-label="Main"
    >
      <div className="text-page-title text-lg md:text-xl">How&apos;s Grandma?</div>
      <div className="mt-3 flex flex-wrap items-center justify-center gap-3 md:mt-0 md:gap-4">
        {items.map(({ href, label }) => {
          const active =
            pathname === href ||
            (href !== "/dashboard" &&
              pathname.toLowerCase() === href.toLowerCase());
          return (
            <Link
              key={href}
              href={href}
              className={`${navLinkBase} ${active ? "bg-[var(--accent-muted)]/60 ring-emerald-600/20" : ""}`}
              aria-current={active ? "page" : undefined}
            >
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
