import { NextResponse } from "next/server";

const DEFAULT_CV_BASE = "http://127.0.0.1:8080";

function cvBaseUrl(): string {
  const raw = process.env.CV_API_BASE?.trim() || DEFAULT_CV_BASE;
  return raw.replace(/\/$/, "");
}

export async function GET() {
  try {
    const upstream = new URL("/api/primary-state", `${cvBaseUrl()}/`);
    const response = await fetch(upstream.toString(), {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });

    const data = await response.json().catch(() => ({
      error: "Invalid JSON from CV server",
    }));
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json(
      { error: "Failed to connect to CV server" },
      { status: 500 },
    );
  }
}
