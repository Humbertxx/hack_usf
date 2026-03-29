"use client";

import { HACK_USF_DEMO_SESSION_KEY } from "@/lib/demo-session";
import { useEffect } from "react";
import { useOldPeopleContext } from "../OldPeopleContext";

/** After reload, restore navbar + duo context when the demo session flag is set. */
export default function DemoSessionBootstrap() {
  const { setNavbar, setOldPeople } = useOldPeopleContext();

  useEffect(() => {
    if (sessionStorage.getItem(HACK_USF_DEMO_SESSION_KEY) !== "1") return;
    setNavbar(true);
    setOldPeople(3);
  }, [setNavbar, setOldPeople]);

  return null;
}
