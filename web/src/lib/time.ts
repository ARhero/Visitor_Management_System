// The API always speaks UTC; people always read IST.
export const IST = "Asia/Kolkata";

const dt = new Intl.DateTimeFormat("en-IN", {
  timeZone: IST,
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: true,
});

export function formatIST(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dt.format(new Date(iso));
}

export function formatPhone(e164: string | null | undefined): string {
  if (!e164) return "—";
  const m = /^\+91(\d{5})(\d{5})$/.exec(e164);
  return m ? `+91 ${m[1]} ${m[2]}` : e164;
}
