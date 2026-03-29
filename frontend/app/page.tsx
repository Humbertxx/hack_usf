"use client";

import Image from "next/image";
import { useRef, useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { useOldPeopleContext } from "./OldPeopleContext";
import { enrollmentSuccessDashboardHref } from "@/lib/enrollment-flags";
import { getPreferredVideoStream } from "@/lib/getPreferredVideoStream";

type DuoStep = "idle" | "grandma" | "grandpa";

function canvasToJpegBlob(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/jpeg");
  });
}

export default function Home() {
  const router = useRouter();
  const { oldPeople, setOldPeople } = useOldPeopleContext();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [isCameraActive, setIsCameraActive] = useState(false);
  const [duoStep, setDuoStep] = useState<DuoStep>("idle");
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [isEnrolling, setIsEnrolling] = useState(false);

  useEffect(() => {
    if (oldPeople !== 3) {
      setDuoStep("idle");
    }
  }, [oldPeople]);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let cancelled = false;

    if (isCameraActive) {
      (async () => {
        try {
          const s = await getPreferredVideoStream();
          if (cancelled) {
            s.getTracks().forEach((t) => t.stop());
            return;
          }
          stream = s;
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
          }
        } catch (err) {
          console.error("Error accessing webcam:", err);
          setIsCameraActive(false);
        }
      })();
    }

    return () => {
      cancelled = true;
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
    };
  }, [isCameraActive]);

  const stopVideoTracks = useCallback(() => {
    const v = videoRef.current;
    const src = v?.srcObject;
    if (src instanceof MediaStream) {
      src.getTracks().forEach((t) => t.stop());
    }
    if (v) {
      v.srcObject = null;
    }
  }, []);

  const captureAndEnroll = async (subjectId: "grandma" | "grandpa") => {
    const canvas = canvasRef.current;
    const video = videoRef.current;

    if (!canvas || !video || isEnrolling) return;

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);

    const blob = await canvasToJpegBlob(canvas);
    if (!blob) {
      setEnrollError("Could not capture image.");
      return;
    }

    const formData = new FormData();
    formData.append("file", blob, "enroll.jpg");
    formData.append("subject_id", subjectId);
    formData.append(
      "display_name",
      subjectId === "grandma" ? "Grandma" : "Grandpa",
    );
    formData.append(
      "color",
      subjectId === "grandma" ? "#FF6B6B" : "#4ECDC4",
    );

    setIsEnrolling(true);
    setEnrollError(null);

    try {
      const res = await fetch("/api/enroll", {
        method: "POST",
        body: formData,
      });

      let body: unknown;
      try {
        body = await res.json();
      } catch {
        setEnrollError("Invalid response from server.");
        return;
      }

      if (!res.ok) {
        const detail = (body as { detail?: unknown })?.detail;
        const msg =
          typeof detail === "string"
            ? detail
            : Array.isArray(detail) && detail[0]?.msg
              ? String(detail[0].msg)
              : typeof (body as { error?: string })?.error === "string"
                ? (body as { error: string }).error
                : `Enrollment failed (${res.status})`;
        setEnrollError(msg);
        return;
      }

      if (oldPeople === 3 && subjectId === "grandma") {
        setDuoStep("grandpa");
        return;
      }

      stopVideoTracks();
      setIsCameraActive(false);
      setDuoStep("idle");
      router.push(enrollmentSuccessDashboardHref());
    } finally {
      setIsEnrolling(false);
    }
  };

  const grandpa = () => {
    if (duoStep !== "idle") return;
    if (oldPeople === 2) setOldPeople(0);
    else if (oldPeople === 1) setOldPeople(3);
    else if (oldPeople === 3) setOldPeople(1);
    else setOldPeople(2);
  };

  const grandma = () => {
    if (duoStep !== "idle") return;
    if (oldPeople === 1) setOldPeople(0);
    else if (oldPeople === 2) setOldPeople(3);
    else if (oldPeople === 3) setOldPeople(2);
    else setOldPeople(1);
  };

  const startDuo = () => {
    setDuoStep("grandma");
    setIsCameraActive(true);
    setEnrollError(null);
  };

  const cancelCamera = () => {
    stopVideoTracks();
    setIsCameraActive(false);
    setDuoStep("idle");
    setEnrollError(null);
  };

  const toggleLocked = duoStep !== "idle";

  return (
    <>
      <div className="flex flex-col items-center justify-center w-screen mt-10 gap-5">
        <div className="text-center max-w-xl">
          <p className="font-bold text-lg md:text-xl lg:text-3xl">
            {isCameraActive
              ? "Step back — fit full body in frame"
              : "Welcome to Enrollment! Choose family members to enroll below."}
          </p>
          {isCameraActive && oldPeople === 3 && duoStep === "grandpa" && (
            <p className="mt-2 text-base md:text-lg text-sky-800 font-medium">
              Next: Grandpa
            </p>
          )}
        </div>

        <div className="relative w-[400px] h-[400px]">
          {isCameraActive ? (
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="w-full h-full object-cover rounded-2xl shadow border-4 border-sky-200"
            />
          ) : (
            <Image
              src="/oldpeople.jpg"
              alt="Family"
              width={400}
              height={400}
              className="w-full h-full object-cover rounded-2xl shadow"
            />
          )}
          <canvas ref={canvasRef} className="hidden" />
        </div>

        <div
          className={`shadow flex justify-center items-center bg-sky-50 rounded-2xl w-[300px] h-[50px] ${toggleLocked ? "opacity-50 pointer-events-none" : ""}`}
        >
          <button
            type="button"
            onClick={() => grandma()}
            disabled={toggleLocked}
            className={`hover:shadow bg-sky-50 w-[50%] h-full rounded-l-2xl hover:scale-105 transition duration-100 ease-in disabled:hover:scale-100 ${oldPeople === 1 || oldPeople === 3 ? "bg-sky-200" : ""}`}
          >
            grandma
          </button>
          <button
            type="button"
            onClick={() => grandpa()}
            disabled={toggleLocked}
            className={`hover:shadow bg-sky-50 w-[50%] h-full rounded-r-2xl hover:scale-105 transition duration-100 ease-in disabled:hover:scale-100 ${oldPeople === 2 || oldPeople === 3 ? "bg-sky-200" : ""}`}
          >
            grandpa
          </button>
        </div>

        {enrollError && (
          <p className="text-red-600 text-sm max-w-md text-center" role="alert">
            {enrollError}
          </p>
        )}

        <div className="flex flex-col items-center justify-center gap-5">
          {oldPeople === 0 && (
            <div className="bg-sky-50 p-5 rounded-lg shadow">
              <p className="font-bold text-lg">No One Selected!</p>
            </div>
          )}
          {oldPeople === 1 && (
            <button
              type="button"
              disabled={isEnrolling}
              onClick={() =>
                isCameraActive
                  ? void captureAndEnroll("grandma")
                  : setIsCameraActive(true)
              }
              className="bg-sky-100 p-5 rounded-lg shadow hover:scale-110 transition border-2 border-sky-300 disabled:opacity-50 disabled:hover:scale-100"
            >
              <p className="font-bold text-lg">
                {isCameraActive
                  ? "Capture Grandma"
                  : "Start Grandma Enrollment"}
              </p>
            </button>
          )}

          {oldPeople === 2 && (
            <button
              type="button"
              disabled={isEnrolling}
              onClick={() =>
                isCameraActive
                  ? void captureAndEnroll("grandpa")
                  : setIsCameraActive(true)
              }
              className="bg-sky-100 p-5 rounded-lg shadow hover:scale-110 transition border-2 border-sky-300 disabled:opacity-50 disabled:hover:scale-100"
            >
              <p className="font-bold text-lg">
                {isCameraActive
                  ? "Capture Grandpa"
                  : "Start Grandpa Enrollment"}
              </p>
            </button>
          )}

          {oldPeople === 3 && duoStep === "idle" && (
            <button
              type="button"
              onClick={startDuo}
              className="bg-sky-100 p-5 rounded-lg shadow hover:scale-110 transition border-2 border-sky-300"
            >
              <p className="font-bold text-lg">Start Duo Enrollment</p>
            </button>
          )}

          {oldPeople === 3 && duoStep === "grandma" && isCameraActive && (
            <button
              type="button"
              disabled={isEnrolling}
              onClick={() => void captureAndEnroll("grandma")}
              className="bg-sky-100 p-5 rounded-lg shadow hover:scale-110 transition border-2 border-sky-300 disabled:opacity-50 disabled:hover:scale-100"
            >
              <p className="font-bold text-lg">Capture Grandma</p>
            </button>
          )}

          {oldPeople === 3 && duoStep === "grandpa" && isCameraActive && (
            <button
              type="button"
              disabled={isEnrolling}
              onClick={() => void captureAndEnroll("grandpa")}
              className="bg-sky-100 p-5 rounded-lg shadow hover:scale-110 transition border-2 border-sky-300 disabled:opacity-50 disabled:hover:scale-100"
            >
              <p className="font-bold text-lg">Capture Grandpa</p>
            </button>
          )}

          {isCameraActive && (
            <button
              type="button"
              onClick={cancelCamera}
              className="text-gray-500 underline text-sm"
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    </>
  );
}
