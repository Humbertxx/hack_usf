import { NextResponse } from "next/server";

const DEFAULT_CV_BASE = "http://127.0.0.1:8080";

function cvBaseUrl(): string {
  const raw = process.env.CV_API_BASE?.trim() || DEFAULT_CV_BASE;
  return raw.replace(/\/$/, "");
}

export async function POST(request: Request) {
  try {
    const body = await request.json().catch(() => null);
    if (!body || typeof body.message !== "string") {
      return NextResponse.json(
        { error: "Request body must include message" },
        { status: 400 },
      );
    }

    const upstream = new URL("/api/insights-chat", `${cvBaseUrl()}/`);
    const response = await fetch(upstream.toString(), {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(body),
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
