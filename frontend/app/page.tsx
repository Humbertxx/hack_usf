"use client";

import Image from "next/image";
import { useRef, useState, useEffect, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useOldPeopleContext } from "./OldPeopleContext";
import { enrollmentSuccessDashboardHref } from "@/lib/enrollment-flags";
import { getPreferredVideoStream } from "@/lib/getPreferredVideoStream";

type DuoStep = "idle" | "grandma" | "grandpa";

const PHOTO_STEPS = [
  {
    key: "front",
    title: "Front view",
    hint: "Face the camera with arms relaxed at your sides.",
  },
  {
    key: "side",
    title: "Side view",
    hint: "Turn 90° so we see your profile (left or right side).",
  },
  {
    key: "back",
    title: "Back view",
    hint: "Turn so your back faces the camera.",
  },
] as const;

function PoseGuideSvg({ variant }: { variant: "front" | "side" | "back" }) {
  const stroke = "currentColor";
  const common = "w-28 h-36 mx-auto text-sky-800/80";
  if (variant === "front") {
    return (
      <svg className={common} viewBox="0 0 80 120" aria-hidden>
        <circle cx="40" cy="18" r="10" fill="none" stroke={stroke} strokeWidth="2.5" />
        <path
          d="M40 28 L40 62 M22 42 L58 42 M40 62 L28 98 M40 62 L52 98 M28 98 L24 112 M52 98 L56 112"
          fill="none"
          stroke={stroke}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  if (variant === "side") {
    return (
      <svg className={common} viewBox="0 0 80 120" aria-hidden>
        <ellipse cx="48" cy="18" rx="9" ry="11" fill="none" stroke={stroke} strokeWidth="2.5" />
        <path
          d="M42 28 Q32 44 32 60 L35 88 M35 88 L32 108 M35 88 L48 108"
          fill="none"
          stroke={stroke}
          strokeWidth="2.5"
          strokeLinecap="round"
        />
      </svg>
    );
  }
  return (
    <svg className={common} viewBox="0 0 80 120" aria-hidden>
      <circle cx="40" cy="18" r="10" fill="none" stroke={stroke} strokeWidth="2.5" />
      <path
        d="M40 28 L40 62 M28 44 L52 44 M40 62 L30 96 M40 62 L50 96 M30 96 L26 110 M50 96 L54 110"
        fill="none"
        stroke={stroke}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path d="M22 38 L18 48" stroke={stroke} strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function canvasToJpegBlob(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), "image/jpeg");
  });
}

export default function Home() {
  const router = useRouter();
  const { oldPeople, setOldPeople, setNavbar } = useOldPeopleContext();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  const [isCameraActive, setIsCameraActive] = useState(false);
  const [duoStep, setDuoStep] = useState<DuoStep>("idle");
  const [enrollPhotoStep, setEnrollPhotoStep] = useState(1);
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [isEnrolling, setIsEnrolling] = useState(false);
  /** 3 → 1 while waiting before shutter; null when idle */
  const [captureCountdown, setCaptureCountdown] = useState<number | null>(null);
  const captureCountdownAbortRef = useRef(false);
  /** True from first capture tap through countdown + upload (avoids double-starts before state updates). */
  const shutterSequenceRef = useRef(false);

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

  const startCameraWithReset = useCallback(() => {
    captureCountdownAbortRef.current = true;
    shutterSequenceRef.current = false;
    setCaptureCountdown(null);
    setEnrollPhotoStep(1);
    setEnrollError(null);
    setIsCameraActive(true);
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
    formData.append("file", blob, `enroll-step${enrollPhotoStep}.jpg`);
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

      if (enrollPhotoStep < 3) {
        setEnrollPhotoStep((s) => s + 1);
        return;
      }

      if (oldPeople === 3 && subjectId === "grandma") {
        setDuoStep("grandpa");
        setEnrollPhotoStep(1);
        return;
      }

      stopVideoTracks();
      setIsCameraActive(false);
      setDuoStep("idle");
      setNavbar(true);
      router.push(enrollmentSuccessDashboardHref());
    } finally {
      setIsEnrolling(false);
    }
  };

  const waitCaptureCountdown = async (): Promise<boolean> => {
    captureCountdownAbortRef.current = false;
    for (let n = 3; n >= 1; n--) {
      if (captureCountdownAbortRef.current) {
        setCaptureCountdown(null);
        return false;
      }
      setCaptureCountdown(n);
      await new Promise<void>((resolve) => {
        setTimeout(resolve, 1000);
      });
    }
    if (captureCountdownAbortRef.current) {
      setCaptureCountdown(null);
      return false;
    }
    setCaptureCountdown(null);
    return true;
  };

  const captureAfterCountdown = async (subjectId: "grandma" | "grandpa") => {
    if (isEnrolling || shutterSequenceRef.current) return;
    shutterSequenceRef.current = true;
    try {
      const proceed = await waitCaptureCountdown();
      if (!proceed) return;
      await captureAndEnroll(subjectId);
    } finally {
      shutterSequenceRef.current = false;
    }
  };

  const grandpa = () => {
    if (duoStep !== "idle" || isCameraActive) return;
    if (oldPeople === 2) setOldPeople(0);
    else if (oldPeople === 1) setOldPeople(3);
    else if (oldPeople === 3) setOldPeople(1);
    else setOldPeople(2);
  };

  const grandma = () => {
    if (duoStep !== "idle" || isCameraActive) return;
    if (oldPeople === 1) setOldPeople(0);
    else if (oldPeople === 2) setOldPeople(3);
    else if (oldPeople === 3) setOldPeople(2);
    else setOldPeople(1);
  };

  const startDuo = () => {
    setDuoStep("grandma");
    startCameraWithReset();
  };

  const cancelCamera = () => {
    captureCountdownAbortRef.current = true;
    shutterSequenceRef.current = false;
    setCaptureCountdown(null);
    stopVideoTracks();
    setIsCameraActive(false);
    setDuoStep("idle");
    setEnrollPhotoStep(1);
    setEnrollError(null);
  };

  const isCaptureBusy = isEnrolling || captureCountdown !== null;
  const toggleLocked = duoStep !== "idle" || isCameraActive;
  const enrollingLabel = useMemo(() => {
    if (!isCameraActive) return null;
    if (oldPeople === 1) return "Enrolling Grandma";
    if (oldPeople === 2) return "Enrolling Grandpa";
    if (oldPeople === 3 && duoStep === "grandma") return "Duo flow · Grandma (1 of 2)";
    if (oldPeople === 3 && duoStep === "grandpa") return "Duo flow · Grandpa (2 of 2)";
    return null;
  }, [isCameraActive, oldPeople, duoStep]);
  const stepMeta = PHOTO_STEPS[enrollPhotoStep - 1];
  const guideVariant = stepMeta.key;
  const enrollActionClass =
    "w-full max-w-sm rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface)] p-5 text-neutral-900 shadow-sm ring-1 ring-[var(--ring-subtle)] transition hover:shadow-md disabled:opacity-50 disabled:hover:shadow-sm";

  return (
    <>
      <div className="mt-10 flex w-full flex-col items-center justify-center gap-5 px-4 sm:px-6">
        <div className="text-center max-w-xl px-3">
          <p className="font-bold text-lg md:text-xl lg:text-3xl">
            {isCameraActive
              ? `${stepMeta.title} · Step ${enrollPhotoStep} of 3`
              : "Welcome to Enrollment! Choose family members to enroll below."}
          </p>
          {isCameraActive && (
            <>
              <p className="mt-2 text-base md:text-lg text-sky-900">
                Step back — fit full body in frame.
              </p>
              <p className="mt-1 text-base md:text-lg text-sky-800/90">
                {stepMeta.hint}
              </p>
              <div className="mt-3 flex justify-center">
                <PoseGuideSvg variant={guideVariant} />
              </div>
            </>
          )}
          {isCameraActive &&
            oldPeople === 3 &&
            duoStep === "grandpa" &&
            enrollPhotoStep === 1 && (
              <p className="mt-2 text-base md:text-lg text-sky-800 font-medium">
                Now enrolling Grandpa — same 3 poses
              </p>
            )}
        </div>

        <div className="relative aspect-square w-full max-w-[400px]">
          {isCameraActive ? (
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="h-full w-full rounded-2xl border border-[var(--border-subtle)] object-cover shadow-sm ring-1 ring-[var(--ring-subtle)]"
            />
          ) : (
            <Image
              src="/oldpeople.jpg"
              alt="Family"
              width={400}
              height={400}
              priority
              className="h-full w-full rounded-2xl border border-[var(--border-subtle)] object-cover shadow-sm ring-1 ring-[var(--ring-subtle)]"
            />
          )}
          {isCameraActive && captureCountdown !== null && (
            <div
              className="absolute inset-0 flex flex-col items-center justify-center rounded-2xl bg-black/45 pointer-events-none"
              aria-live="polite"
            >
              <span className="text-8xl font-bold text-white tabular-nums leading-none drop-shadow-lg">
                {captureCountdown}
              </span>
              <span className="mt-4 text-lg font-medium text-white/95">Hold still…</span>
            </div>
          )}
          <canvas ref={canvasRef} className="hidden" />
        </div>

        {isCameraActive && enrollingLabel ? (
          <p className="text-center text-sky-900 font-semibold text-base max-w-sm px-2">
            {enrollingLabel}
          </p>
        ) : (
          <div
            className={`flex h-12 w-full max-w-[320px] items-center justify-center rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface)] shadow-sm ring-1 ring-[var(--ring-subtle)] ${toggleLocked ? "pointer-events-none opacity-50" : ""}`}
          >
            <button
              type="button"
              onClick={() => grandma()}
              disabled={toggleLocked}
              className={`h-full w-1/2 rounded-l-2xl bg-[var(--surface)] text-sm font-medium transition hover:bg-[var(--surface-muted)] ${oldPeople === 1 || oldPeople === 3 ? "bg-[var(--surface-muted)] text-neutral-900" : "text-neutral-700"}`}
            >
              Grandma
            </button>
            <button
              type="button"
              onClick={() => grandpa()}
              disabled={toggleLocked}
              className={`h-full w-1/2 rounded-r-2xl bg-[var(--surface)] text-sm font-medium transition hover:bg-[var(--surface-muted)] ${oldPeople === 2 || oldPeople === 3 ? "bg-[var(--surface-muted)] text-neutral-900" : "text-neutral-700"}`}
            >
              Grandpa
            </button>
          </div>
        )}

        {enrollError && (
          <p className="text-red-600 text-sm max-w-md text-center" role="alert">
            {enrollError}
          </p>
        )}

        <div className="flex flex-col items-center justify-center gap-5">
          {oldPeople === 0 && (
            <div className="w-full max-w-sm rounded-2xl border border-[var(--border-subtle)] bg-[var(--surface)] p-5 text-center shadow-sm ring-1 ring-[var(--ring-subtle)]">
              <p className="font-bold text-lg">No One Selected!</p>
            </div>
          )}
          {oldPeople === 1 && (
            <button
              type="button"
              disabled={isCaptureBusy}
              onClick={() =>
                isCameraActive
                  ? void captureAfterCountdown("grandma")
                  : startCameraWithReset()
              }
              className={enrollActionClass}
            >
              <p className="font-bold text-lg">
                {isCameraActive
                  ? enrollPhotoStep < 3
                    ? `Capture step ${enrollPhotoStep}`
                    : "Capture final photo"
                  : "Start Grandma Enrollment"}
              </p>
              {isCameraActive && (
                <p className="mt-1 text-center text-sm text-neutral-600">
                  3 quick photos for better recognition
                </p>
              )}
            </button>
          )}

          {oldPeople === 2 && (
            <button
              type="button"
              disabled={isCaptureBusy}
              onClick={() =>
                isCameraActive
                  ? void captureAfterCountdown("grandpa")
                  : startCameraWithReset()
              }
              className={enrollActionClass}
            >
              <p className="font-bold text-lg">
                {isCameraActive
                  ? enrollPhotoStep < 3
                    ? `Capture step ${enrollPhotoStep}`
                    : "Capture final photo"
                  : "Start Grandpa Enrollment"}
              </p>
              {isCameraActive && (
                <p className="mt-1 text-center text-sm text-neutral-600">
                  3 quick photos for better recognition
                </p>
              )}
            </button>
          )}

          {oldPeople === 3 && duoStep === "idle" && (
            <button
              type="button"
              onClick={startDuo}
              className={enrollActionClass}
            >
              <p className="font-bold text-lg">Start Duo Enrollment</p>
              <p className="mt-1 text-center text-sm text-neutral-600">
                3 photos each person
              </p>
            </button>
          )}

          {oldPeople === 3 && duoStep === "grandma" && isCameraActive && (
            <button
              type="button"
              disabled={isCaptureBusy}
              onClick={() => void captureAfterCountdown("grandma")}
              className={enrollActionClass}
            >
              <p className="font-bold text-lg">
                {enrollPhotoStep < 3
                  ? `Capture Grandma · step ${enrollPhotoStep}`
                  : "Capture Grandma · final photo"}
              </p>
            </button>
          )}

          {oldPeople === 3 && duoStep === "grandpa" && isCameraActive && (
            <button
              type="button"
              disabled={isCaptureBusy}
              onClick={() => void captureAfterCountdown("grandpa")}
              className={enrollActionClass}
            >
              <p className="font-bold text-lg">
                {enrollPhotoStep < 3
                  ? `Capture Grandpa · step ${enrollPhotoStep}`
                  : "Capture Grandpa · final photo"}
              </p>
            </button>
          )}

          {isCameraActive && (
            <button
              type="button"
              onClick={cancelCamera}
              className="rounded-sm text-sm text-neutral-600 underline underline-offset-4 transition hover:text-neutral-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-600/40"
            >
              Cancel
            </button>
          )}
        </div>
      </div>
    </>
  );
}
