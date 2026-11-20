/**
 * Shrink a camera photo before upload: about 640 px, WebP (JPEG where WebP encoding
 * isn't supported). A 4 MB phone photo becomes roughly 40 KB, which matters on 3G.
 * The server re-encodes again and strips all metadata; this step is only for speed.
 */
export async function compressImage(file: Blob, maxSide = 640): Promise<Blob> {
  const bitmap = await createImageBitmap(file, { imageOrientation: "from-image" } as ImageBitmapOptions).catch(() => null);
  if (!bitmap) return file; // let the server decide (it rejects non-images)
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const w = Math.round(bitmap.width * scale);
  const h = Math.round(bitmap.height * scale);
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, w, h);
  bitmap.close();
  const toBlob = (type: string) => new Promise<Blob | null>((res) => canvas.toBlob(res, type, 0.8));
  const webp = await toBlob("image/webp");
  if (webp && webp.type === "image/webp") return webp;
  return (await toBlob("image/jpeg")) ?? file;
}
