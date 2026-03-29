"use client";

import { HACK_USF_DEMO_SESSION_KEY } from "@/lib/demo-session";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useOldPeopleContext } from "../OldPeopleContext";

export default function DemoPage() {
  const router = useRouter();
  const { setNavbar, setOldPeople } = useOldPeopleContext();

  useEffect(() => {
    sessionStorage.setItem(HACK_USF_DEMO_SESSION_KEY, "1");
    setOldPeople(3);
    setNavbar(true);
    router.replace("/dashboard");
  }, [router, setNavbar, setOldPeople]);

  return (
    <div className="text-body-reading flex min-h-[40vh] flex-col items-center justify-center gap-2 px-6 text-neutral-600">
      <p className="text-sm">Opening dashboard in demo mode…</p>
    </div>
  );
}
