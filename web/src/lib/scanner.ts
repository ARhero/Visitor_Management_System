/**
 * Camera QR scanning. Uses the browser's BarcodeDetector where it exists (Chrome on
 * Android) and falls back to jsQR, which is only downloaded on devices that need it.
 */

interface Detector {
  detect(source: CanvasImageSource): Promise<{ rawValue: string }[]>;
}

type Decode = (v: HTMLVideoElement) => Promise<string | null>;

async function decoder(): Promise<Decode> {
  const BD = (window as unknown as { BarcodeDetector?: new (o: { formats: string[] }) => Detector }).BarcodeDetector;
  if (BD) {
    try {
      const d = new BD({ formats: ["qr_code"] });
      return async (v) => (await d.detect(v))[0]?.rawValue ?? null;
    } catch {
      /* fall through to jsQR */
    }
  }
  const jsQR = (await import("jsqr")).default;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
  return async (v) => {
    const w = v.videoWidth;
    const h = v.videoHeight;
    if (!w || !h) return null;
    // Decode a centred square at most 720px wide: plenty for a phone-screen QR, and fast.
    const side = Math.min(w, h);
    const size = Math.min(side, 720);
    canvas.width = canvas.height = size;
    ctx.drawImage(v, (w - side) / 2, (h - side) / 2, side, side, 0, 0, size, size);
    const img = ctx.getImageData(0, 0, size, size);
    return jsQR(img.data, size, size, { inversionAttempts: "dontInvert" })?.data ?? null;
  };
}

/** Download the QR decoder now (if this device needs jsQR), so the camera still works
 *  after the connection drops. */
export async function preloadDecoder(): Promise<void> {
  if (!("BarcodeDetector" in window)) await import("jsqr");
}

export interface Scanner {
  stop(): void;
}

/** Start the back camera in ``video`` and call ``onCode`` for each QR read (the same
 *  code is not reported again within 3 seconds). */
export async function startScanner(video: HTMLVideoElement, onCode: (text: string) => void): Promise<Scanner> {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } },
    audio: false,
  });
  video.srcObject = stream;
  video.setAttribute("playsinline", "true");
  await video.play();
  const decode = await decoder();
  let stopped = false;
  let last = "";
  let lastAt = 0;
  const tick = async () => {
    if (stopped) return;
    try {
      const text = await decode(video);
      const now = Date.now();
      if (text && (text !== last || now - lastAt > 3000)) {
        last = text;
        lastAt = now;
        onCode(text);
      }
    } catch {
      /* a frame that can't be read */
    }
    if (!stopped) setTimeout(tick, 180);
  };
  void tick();
  return {
    stop() {
      stopped = true;
      for (const t of stream.getTracks()) t.stop();
      video.srcObject = null;
    },
  };
}
