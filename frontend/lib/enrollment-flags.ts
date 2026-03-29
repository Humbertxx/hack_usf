/**
 * Shared enrollment → dashboard integration contract.
 * @see enrollment_capture_ui plan (Phase 0)
 */

/** Query param name when redirecting after successful enrollment. */
export const ENROLLMENT_QUERY = "enrolled" as const;

/** Query param value that means “finished enrollment, dashboard may run follow-up.” */
export const ENROLLMENT_VALUE = "1" as const;

/**
 * sessionStorage: set after scheduling the delayed POST to /api/start-full-stack
 * so refresh / repeat visits do not re-fire.
 */
export const DASHBOARD_FULL_STACK_FIRED_KEY =
  "hack_usf_dashboard_full_stack_fired" as const;

/** Path + query for router.push after final successful enroll (single or duo). */
export function enrollmentSuccessDashboardHref(): string {
  return `/dashboard?${ENROLLMENT_QUERY}=${ENROLLMENT_VALUE}`;
}

/** For dashboard: true when searchParams indicate post-enrollment landing. */
export function isPostEnrollmentDashboardQuery(
  searchParams: URLSearchParams,
): boolean {
  return searchParams.get(ENROLLMENT_QUERY) === ENROLLMENT_VALUE;
}
