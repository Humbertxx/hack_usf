import { NextResponse } from "next/server";

const DEFAULT_CV_BASE = "http://127.0.0.1:8080";

function cvBaseUrl(): string {
  const raw = process.env.CV_API_BASE?.trim() || DEFAULT_CV_BASE;
  return raw.replace(/\/$/, "");
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const personId = searchParams.get("person_id") ?? "grandma";
    const days = searchParams.get("days") ?? "7";

    const upstream = new URL("/api/insights-trends", `${cvBaseUrl()}/`);
    upstream.searchParams.set("person_id", personId);
    upstream.searchParams.set("days", days);

    const response = await fetch(upstream.toString(), {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });

    const data = await response.json().catch(() => ({
      error: "Invalid JSON from backend server",
    }));
    return NextResponse.json(data, { status: response.status });
  } catch {
    return NextResponse.json(
      { error: "Failed to connect to backend server" },
      { status: 500 },
    );
  }
}
