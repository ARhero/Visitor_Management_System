import { api, downloadFile } from "./api";

/** Phones and tablets: open the PDF at a short-lived address instead of downloading it,
 *  since many phone browsers (e.g. one opened from a WhatsApp link) can't save a file
 *  the page fetched itself, but all of them can show a PDF at an address. */
export const isTouchDevice = () => window.matchMedia?.("(pointer: coarse)").matches ?? false;

export async function openEvacuationPdf(siteId: string | undefined) {
  if (!isTouchDevice()) {
    await downloadFile("/evacuation.pdf", { query: { site_id: siteId || undefined }, fallbackName: "evacuation.pdf" });
    return;
  }
  const { url } = await api<{ url: string }>("/evacuation/pdf-link", { method: "POST", body: { site_id: siteId || null } });
  window.location.assign(url);
}
