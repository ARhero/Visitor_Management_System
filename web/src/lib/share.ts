/**
 * "Share on WhatsApp" from the person's own phone: opens WhatsApp with the message
 * typed in, addressed to ``phone`` if given. Needs no WhatsApp Business account; the
 * person presses send themselves.
 */
export function whatsappShareUrl(text: string, phone?: string | null): string {
  const to = (phone ?? "").replace(/\D/g, "");
  return `https://wa.me/${to}?text=${encodeURIComponent(text)}`;
}

export function openWhatsApp(text: string, phone?: string | null) {
  window.open(whatsappShareUrl(text, phone), "_blank", "noopener");
}
