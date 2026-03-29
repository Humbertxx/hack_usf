/** sessionStorage key: Snowflake-backed demo entry at `/demo`. */
export const HACK_USF_DEMO_SESSION_KEY = "hack_usf_demo" as const;

export function isHackUsfDemoSession(): boolean {
  if (typeof window === "undefined") return false;
  return sessionStorage.getItem(HACK_USF_DEMO_SESSION_KEY) === "1";
}
