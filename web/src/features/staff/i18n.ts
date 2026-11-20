import { useTranslation } from "react-i18next";
import i18n from "@/lib/i18n";
import { ApiError } from "@/lib/api";

// Guard and host screens (bilingual): useS() loads the "staff" strings on demand.

export function useS() {
  return useTranslation("staff");
}

export function errText(e: unknown): string {
  const t = i18n.getFixedT(null, "staff");
  if (e instanceof ApiError) {
    if (e.code === "validation_error" && Array.isArray(e.details) && e.details.length) {
      return (e.details as { loc: string[]; msg: string }[])
        .map((d) => `${d.loc.filter((x) => x !== "body").join(".")}: ${d.msg.replace(/^Value error, /, "")}`)
        .join("\n");
    }
    return e.message || t("errors.generic");
  }
  return t("errors.network");
}

const time = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true });
const dayTime = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });
const day = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short" });

export function clock(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toDateString() === new Date().toDateString() ? time.format(d) : dayTime.format(d);
}
export const shortDay = (iso: string) => day.format(new Date(iso));
export const hhmm = (t: string | null) => (t ? t.slice(0, 5) : "");
