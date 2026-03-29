"use client";

import {
  DASHBOARD_FULL_STACK_FIRED_KEY,
  ENROLLMENT_QUERY,
  ENROLLMENT_VALUE,
} from "@/lib/enrollment-flags";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

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
  const updates: basicstatus[] = [
    { type: "Went to bed", val: "Granny went to bed" },
    { type: "Codin", val: "Granny is currently working hard at the hackathon" },
    { type: "Wishin", val: "Granny is wishing they had better food portions" },
    { type: "Eating", val: "Granny is eating a meal" },
  ];
  const values: basicstatus[] = [
    { type: "Active Hours", val: "8.5" },
    { type: "Sleep Quality", val: "Good" },
    { type: "Exercise", val: "1" },
    { type: "Meals", val: "3" },
  ];

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
          <div>
            <p className="bg-green-500 p-2 rounded">System Status</p>
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
          <div className="flex items-center justify-between w-full">
            <p className="font-bold text-3xl self-start">Live Updates</p>
            <p className="text-xs">Currently Monitoring</p>
          </div>
          {updates.map((item, index) => (
            <div
              key={index}
              className="shadow hover:shadow-xl transition duration-100 ease-in p-3 flex flex-col items-start justify-start bg-sky-50 w-full h-[75px] rounded-2xl"
            >
              <div className="w-full flex justify-between">
                <p className="font-bold text-xl">{item.type}</p>
                <p className="light text-xs text-gray-600">
                  this happened __ minutes ago
                </p>
              </div>
              <p className="text-sm">{item.val}</p>
            </div>
          ))}
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
