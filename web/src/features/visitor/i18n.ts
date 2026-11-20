import { useTranslation } from "react-i18next";
import i18n from "@/lib/i18n";
import { ApiError } from "@/lib/errors";

// Public pages: useT() loads the "visit" strings, in the visitor's language only.

export function useT() {
  return useTranslation("visit");
}

/** Pages a visitor doesn't need on arrival (privacy page, host answer page): their own
 * strings plus the shared visitor ones. */
export function useMoreT() {
  return useTranslation(["visitmore", "visit"], { nsMode: "fallback" });
}

/** Translate a known error code; otherwise fall back to the server's (English) message. */
export function errorText(e: unknown): string {
  const t = i18n.getFixedT(null, "visit");
  if (e instanceof ApiError) {
    const key = `errors.${e.code}`;
    if (i18n.exists(key, { ns: "visit" })) return t(key);
    if (e.code === "invalid_fields" && Array.isArray(e.details)) return e.message;
    return e.message || t("errors.generic");
  }
  return t("errors.network");
}
