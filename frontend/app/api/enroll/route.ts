import { NextResponse } from "next/server";

export async function POST(request: Request) {
  try {
    const formData = await request.formData();

    // Forward the multipart data to the FastAPI CV server
    const response = await fetch("http://localhost:8080/enroll-subject", {
      method: "POST",
      body: formData, // Next.js forwards the boundary and binary data automatically
    });

    const data = await response.json();
    return NextResponse.json(data, { status: response.status });
  } catch (error) {
    return NextResponse.json(
      { error: "Failed to connect to CV server" },
      { status: 500 },
    );
  }
}
