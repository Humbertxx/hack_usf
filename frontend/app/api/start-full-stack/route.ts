import { spawn } from "node:child_process";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const requiredToken = process.env.START_FULL_STACK_TOKEN;
  if (requiredToken) {
    const provided = request.headers.get("x-start-full-stack-token");
    if (provided !== requiredToken) {
      return NextResponse.json(
        { error: "Invalid or missing x-start-full-stack-token" },
        { status: 401 },
      );
    }
  }

  const repoRoot = process.env.HACK_USF_ROOT?.trim();
  if (!repoRoot) {
    return NextResponse.json(
      {
        error:
          "HACK_USF_ROOT is not set. Set it in frontend/.env.local to the absolute path of the hack_usf repository root.",
      },
      { status: 500 },
    );
  }

  /** Single bash -lc string; cwd is HACK_USF_ROOT (repo root). Default runs the full-stack script. */
  const bashLc =
    process.env.HACK_USF_FULL_STACK_LC?.trim() ||
    "exec ./capture/run_full_stack.sh";

  try {
    const child = spawn("bash", ["-lc", bashLc], {
      cwd: repoRoot,
      detached: true,
      stdio: "ignore",
    });
    child.unref();
  } catch {
    return NextResponse.json(
      { error: "Failed to start run_full_stack.sh" },
      { status: 500 },
    );
  }

  return NextResponse.json({ ok: true });
}
