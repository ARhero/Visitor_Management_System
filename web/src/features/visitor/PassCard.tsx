import { useState } from "react";
import { Button } from "@/components/ui";
import { Spinner, cx } from "@/components/ui";
import { formatIST } from "@/lib/time";
import { errorText, useT } from "./i18n";
import { pub, type PassView } from "./publicApi";
import { setLoaded, useLoad } from "./useLoad";
import { Linkified } from "./PublicShell";

const timeOnly = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true });

export function usePass(token: string | undefined) {
  return useLoad(`pass:${token}`, () => pub<PassView>(`/passes/${token}`), { enabled: !!token, refetchInterval: 30_000 });
}

/** The pass a guard looks at: big photo, name, host, QR, and a clear state banner. */
export function PassCard({ token }: { token: string }) {
  const { t } = useT();
  const q = usePass(token);
  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <p className="rounded-lg bg-bad-50 p-4 text-bad">{q.error ? errorText(q.error) : t("pass.invalid")}</p>;
  const p = q.data;
  const ok = p.state === "valid" || p.state === "checked_in";
  const invite = p.kind === "invite";
  const sameDay = new Date(p.valid_until).toDateString() === new Date().toDateString();
  return (
    <article className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm" aria-label={t("pass.title")}>
      <div className="flex items-center justify-between px-5 py-3 text-white" style={{ background: p.branding.primary_color || "var(--color-brand)" }}>
        <span className="text-sm font-medium">{p.org_name}</span>
        <span className="text-xs uppercase tracking-wider opacity-90">{t("pass.title")}</span>
      </div>
      <div className={cx("px-5 py-2 text-center text-sm font-semibold", ok ? "bg-ok-50 text-ok" : "bg-bad-50 text-bad")} role="status">
        {t(`pass.states.${p.state}`)}
      </div>
      <div className="flex items-center gap-4 px-5 pt-5">
        {p.photo_url ? (
          <img src={p.photo_url} alt="" className="size-20 shrink-0 rounded-xl object-cover ring-1 ring-line" />
        ) : (
          <div className="size-20 shrink-0 rounded-xl bg-paper ring-1 ring-line" />
        )}
        <div className="min-w-0">
          <p className="truncate text-xl font-semibold">{p.visitor_name}</p>
          {p.visitor_company && <p className="truncate text-sm text-ink-2">{p.visitor_company}</p>}
          {p.accompanying_count > 0 && <p className="text-sm text-ink-2">{t("pass.people", { n: p.accompanying_count })}</p>}
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-3 px-5 pt-4 text-sm">
        <div><dt className="text-ink-3">{invite ? t("pass.invited") : t("pass.visiting")}</dt><dd className="font-medium">{p.host_name}</dd></div>
        <div><dt className="text-ink-3">{p.site_name}</dt>
          <dd className="font-medium">
            {invite && p.valid_from ? <InviteWindow p={p} /> : t("pass.validUntil", { time: sameDay ? timeOnly.format(new Date(p.valid_until)) : formatIST(p.valid_until) })}
          </dd></div>
      </dl>
      {invite && p.title && <p className="px-5 pt-3 text-sm font-medium">{p.title}</p>}
      {invite && p.needs_consent && <Consent token={token} p={p} />}
      {invite && p.qr_svg && <p className="px-5 pt-3 text-center text-sm text-ink-2">{t("pass.noWait")}</p>}
      {p.qr_svg && (
        <div className="flex justify-center px-5 pt-5">
          {/* Server-generated SVG from our own QR encoder (no user content inside). */}
          <div className="w-64 max-w-full [&>svg]:h-auto [&>svg]:w-full" dangerouslySetInnerHTML={{ __html: p.qr_svg }} data-testid="pass-qr" />
        </div>
      )}
      {(p.directions || p.site_address || p.map_url) && (
        <div className="mx-5 mt-5 rounded-lg bg-paper p-3 text-sm">
          <p className="font-medium">{t("pass.directions")}</p>
          {p.site_address && <p className="mt-1 text-ink-2">{p.site_address}</p>}
          {p.directions && <p className="mt-1 whitespace-pre-line text-ink-2">{p.directions}</p>}
          {p.map_url && <a href={p.map_url} target="_blank" rel="noreferrer" className="mt-2 inline-block font-medium text-brand">{t("pass.openMap")} ↗</a>}
        </div>
      )}
      <div className="h-5" />
    </article>
  );
}

function InviteWindow({ p }: { p: PassView }) {
  const { t } = useT();
  const day = (iso: string) => formatIST(iso).replace(/,? \d.*$/, "");
  if (p.daily_start_time && p.daily_end_time) {
    return <>{day(p.valid_from!)} – {day(p.valid_until)}<br />{t("pass.daily", { from: p.daily_start_time.slice(0, 5), to: p.daily_end_time.slice(0, 5) })}</>;
  }
  return <>{day(p.valid_from!)}<br />{t("pass.window", { from: timeOnly.format(new Date(p.valid_from!)), to: timeOnly.format(new Date(p.valid_until)) })}</>;
}

/** Invited guests never went through check-in, so they accept the privacy notice here
 *  before their QR is shown. */
function Consent({ token, p }: { token: string; p: PassView }) {
  const { t, i18n } = useT();
  const notice = p.notices?.[i18n.language] ?? p.notices?.en;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  async function agree() {
    setBusy(true);
    setError(null);
    try {
      const data = await pub<PassView>(`/passes/${token}/consent`, { body: { notice_id: notice!.id, locale: i18n.language in (p.notices ?? {}) ? i18n.language : "en" } });
      setLoaded(`pass:${token}`, data);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (!notice) return null;
  return (
    <div className="mx-5 mt-5 space-y-3 rounded-lg border border-line p-4" data-testid="pass-consent">
      <p className="text-sm font-medium">{t("pass.consentIntro")}</p>
      <div className="max-h-56 overflow-y-auto whitespace-pre-line rounded bg-paper p-3 text-sm text-ink-2"><Linkified text={notice.body} /></div>
      {error ? <p className="text-sm text-bad">{errorText(error)}</p> : null}
      <Button size="lg" className="w-full" busy={busy} onClick={() => void agree()}>{t("pass.consentAgree")}</Button>
    </div>
  );
}
