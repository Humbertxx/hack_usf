import {
  ENROLLMENT_QUERY,
  ENROLLMENT_VALUE,
  enrollmentSuccessDashboardHref,
} from "./enrollment-flags";

/**
 * Prefer external / USB cameras over built-in / FaceTime after a one-shot permission
 * probe so device labels are available from enumerateDevices.
 *
 * Tied to `./enrollment-flags`: after capture, navigation must use
 * `enrollmentSuccessDashboardHref()` so the dashboard sees the agreed query pair.
 */

function assertEnrollmentRedirectContract(): void {
  if (!ENROLLMENT_QUERY || !ENROLLMENT_VALUE) {
    throw new Error("enrollment-flags: ENROLLMENT_QUERY and ENROLLMENT_VALUE are required");
  }
  const href = enrollmentSuccessDashboardHref();
  if (!href.includes(`${ENROLLMENT_QUERY}=${ENROLLMENT_VALUE}`)) {
    throw new Error("enrollment-flags: enrollmentSuccessDashboardHref must match query contract");
  }
}

function getUserMediaVideo(
  constraints: MediaStreamConstraints,
): Promise<MediaStream> {
  if (typeof navigator === "undefined") {
    return Promise.reject(new Error("navigator is not available"));
  }

  const md = navigator.mediaDevices;
  if (md?.getUserMedia) {
    return md.getUserMedia(constraints);
  }

  const legacy = (
    navigator as Navigator & {
      getUserMedia?: (
        c: MediaStreamConstraints,
        success: (s: MediaStream) => void,
        err: (e: unknown) => void,
      ) => void;
      webkitGetUserMedia?: (
        c: MediaStreamConstraints,
        success: (s: MediaStream) => void,
        err: (e: unknown) => void,
      ) => void;
      mozGetUserMedia?: (
        c: MediaStreamConstraints,
        success: (s: MediaStream) => void,
        err: (e: unknown) => void,
      ) => void;
    }
  ).getUserMedia ??
    (
      navigator as Navigator & {
        webkitGetUserMedia?: (
          c: MediaStreamConstraints,
          success: (s: MediaStream) => void,
          err: (e: unknown) => void,
        ) => void;
      }
    ).webkitGetUserMedia ??
    (
      navigator as Navigator & {
        mozGetUserMedia?: (
          c: MediaStreamConstraints,
          success: (s: MediaStream) => void,
          err: (e: unknown) => void,
        ) => void;
      }
    ).mozGetUserMedia;

  if (!legacy) {
    return Promise.reject(new Error("getUserMedia is not supported"));
  }

  return new Promise((resolve, reject) => {
    legacy.call(navigator, constraints, resolve, reject);
  });
}

/** Lower rank = earlier in list = preferred for capture (external first). */
function videoInputPreferenceRank(device: MediaDeviceInfo): number {
  const label = device.label.toLowerCase();

  if (
    label.includes("usb") ||
    label.includes("uvc") ||
    label.includes("hdmi") ||
    label.includes("capture card") ||
    label.includes("cam link") ||
    label.includes("elgato") ||
    label.includes("obs virtual") ||
    label.includes("external")
  ) {
    return 0;
  }

  if (
    label.includes("facetime") ||
    label.includes("built-in") ||
    label.includes("built in") ||
    label.includes("integrated camera") ||
    label.includes("integrated webcam") ||
    label.includes("isight") ||
    label.includes("surface camera") ||
    label.includes("truevision") ||
    label.includes("user-facing") ||
    label.includes("front camera")
  ) {
    return 2;
  }

  return 1;
}

function compareVideoInputs(a: MediaDeviceInfo, b: MediaDeviceInfo): number {
  const dr =
    videoInputPreferenceRank(a) - videoInputPreferenceRank(b);
  if (dr !== 0) return dr;
  return a.deviceId.localeCompare(b.deviceId);
}

/**
 * Opens the best-effort “full body” camera stream: external-like devices before
 * built-in / FaceTime. Falls back to default video if enumeration or constraints fail.
 */
export async function getPreferredVideoStream(): Promise<MediaStream> {
  assertEnrollmentRedirectContract();

  if (typeof navigator === "undefined") {
    throw new Error("navigator is not available");
  }

  const md = navigator.mediaDevices;
  if (!md?.enumerateDevices || !md.getUserMedia) {
    return getUserMediaVideo({ video: true });
  }

  let probe: MediaStream | undefined;
  try {
    probe = await md.getUserMedia({ video: true });
  } catch (e) {
    throw e;
  } finally {
    probe?.getTracks().forEach((t) => t.stop());
  }

  const inputs = (await md.enumerateDevices()).filter(
    (d) => d.kind === "videoinput",
  );

  if (inputs.length === 0) {
    return md.getUserMedia({ video: true });
  }

  const sorted = [...inputs].sort(compareVideoInputs);
  const chosen = sorted[0]!;

  const videoConstraints: MediaTrackConstraints = {
    width: { ideal: 1280 },
    height: { ideal: 720 },
  };
  if (chosen.deviceId) {
    videoConstraints.deviceId = { ideal: chosen.deviceId };
  }

  try {
    return await md.getUserMedia({ video: videoConstraints });
  } catch {
    return md.getUserMedia({ video: true });
  }
}
