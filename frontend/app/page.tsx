"use client";

import Image from "next/image";
import { useContext, useRef, useState, useEffect } from "react";
import { OldPeopleContext, useOldPeopleContext } from "./OldPeopleContext";

export default function Home() {
  const { oldPeople, setOldPeople } = useOldPeopleContext();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // state to track camera state
  const [isCameraActive, setIsCameraActive] = useState(false);

  // webcame to start/stop webcame
  useEffect(() => {
    let stream: MediaStream | null = null;

    if (isCameraActive) {
      const startVideo = async () => {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video: true });
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
          }
        } catch (err) {
          console.error("Error accessing webcam:", err);
          setIsCameraActive(false);
        }
      };
      startVideo();
    }

    return () => {
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
    };
  }, [isCameraActive]);

  const captureAndEnroll = async (subjectId: "grandma" | "grandpa") => {
    const canvas = canvasRef.current;
    const video = videoRef.current;

    if (canvas && video) {
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      canvas
        .getContext("2d")
        ?.drawImage(video, 0, 0, canvas.width, canvas.height);

      canvas.toBlob(async (blob) => {
        if (!blob) return;

        const formData = new FormData();
        formData.append("file", blob, "enroll.jpg");
        formData.append("subject_id", subjectId);
        formData.append(
          "display_name",
          subjectId === "grandma" ? "Grandma" : "Grandpa",
        );
        formData.append("color", "#FF6B6B");

        const res = await fetch("/api/enroll", {
          method: "POST",
          body: formData,
        });

        const result = await res.json();
        console.log("Enrollment Success:", result);

        // camera close after capture
        // setIsCameraActive(false);
      }, "image/jpeg");
    }
  };

  const grandpa = () => {
    if (oldPeople === 2) setOldPeople(0);
    else if (oldPeople === 1) setOldPeople(3);
    else if (oldPeople === 3) setOldPeople(1);
    else setOldPeople(2);
  };

  const grandma = () => {
    if (oldPeople === 1) setOldPeople(0);
    else if (oldPeople === 2) setOldPeople(3);
    else if (oldPeople === 3) setOldPeople(2);
    else setOldPeople(1);
  };

  return (
    <>
      <div className="flex flex-col items-center justify-center w-screen mt-10 gap-5">
        <p className="font-bold text-lg md:text-xl lg:text-3xl text-center">
          {isCameraActive
            ? "Align face in the frame"
            : "Welcome to Enrollment! Choose family members to enroll below."}
        </p>

        <div className="relative w-[400px] h-[400px]">
          {isCameraActive ? (
            <video
              ref={videoRef}
              autoPlay
              playsInline
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
          {/* canvas for capturing frames*/}
          <canvas ref={canvasRef} className="hidden" />
        </div>

        <div className="shadow flex justify-center items-center bg-sky-50 rounded-2xl w-[300px] h-[50px]">
          <button
            onClick={() => grandma()}
            className={`hover:shadow bg-sky-50 w-[50%] h-full rounded-l-2xl hover:scale-105 transition duration-100 ease-in ${oldPeople === 1 || oldPeople === 3 ? "bg-sky-200" : ""}`}
          >
            grandma
          </button>
          <button
            onClick={() => grandpa()}
            className={`hover:shadow bg-sky-50 w-[50%] h-full rounded-r-2xl hover:scale-105 transition duration-100 ease-in ${oldPeople === 2 || oldPeople === 3 ? "bg-sky-200" : ""}`}
          >
            grandpa
          </button>
        </div>

        <div className="flex flex-col items-center justify-center gap-5">
          {oldPeople === 0 && (
            <div className="bg-sky-50 p-5 rounded-lg shadow">
              <p className="font-bold text-lg">No One Selected!</p>
            </div>
          )}
          {oldPeople === 1 && (
            <button
              onClick={() =>
                isCameraActive
                  ? captureAndEnroll("grandma")
                  : setIsCameraActive(true)
              }
              className="bg-sky-100 p-5 rounded-lg shadow hover:scale-110 transition border-2 border-sky-300"
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
              onClick={() =>
                isCameraActive
                  ? captureAndEnroll("grandpa")
                  : setIsCameraActive(true)
              }
              className="bg-sky-100 p-5 rounded-lg shadow hover:scale-110 transition border-2 border-sky-300"
            >
              <p className="font-bold text-lg">
                {isCameraActive
                  ? "Capture Grandpa"
                  : "Start Grandpa Enrollment"}
              </p>
            </button>
          )}

          {oldPeople === 3 && (
            <>
              <button
                onClick={() => captureAndEnroll("grandma")}
                className={`bg-sky-100 p-5 rounded-lg shadow hover:scale-110 transition border-2 border-sky-300 ${isCameraActive ? "" : "hidden"}`}
              >
                <p className="font-bold text-lg">Capture Grandma</p>
              </button>
              <button
                onClick={() => captureAndEnroll("grandpa")}
                className={`bg-sky-100 p-5 rounded-lg shadow hover:scale-110 transition border-2 border-sky-300 ${isCameraActive ? "" : "hidden"}`}
              >
                <p className="font-bold text-lg">Capture Grandpa</p>
              </button>
              <button
                onClick={() => setIsCameraActive(true)}
                className={`bg-sky-100 p-5 rounded-lg shadow hover:scale-110 transition border-2 border-sky-300 ${isCameraActive ? "hidden" : ""}`}
              >
                <p className="font-bold text-lg">Start Duo Enrollment</p>
              </button>
            </>
          )}

          {isCameraActive && (
            <button
              onClick={() => setIsCameraActive(false)}
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
