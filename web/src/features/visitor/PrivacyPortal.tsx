import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "react-router";
import { Spinner } from "@/components/ui";
import { ApiError } from "@/lib/errors";
import { errorText, useMoreT } from "./i18n";
import { BigButton, Linkified, Panel, PublicShell } from "./PublicShell";
import { pub, store } from "./publicApi";

/** /privacy/:slug — a visitor sees, downloads or asks to erase their data (DPDP s.11–12).
 *  They prove it's their number with a WhatsApp OTP; the token lasts 20 minutes. */

interface PageInfo { org_name: string; logo_url: string | null; primary_color: string; retention_days: number; privacy_contact: string | null; notices: Record<string, string>; self_serve?: boolean }
interface Visit { id: string; requested_at: string; site: string | null; host: string | null; purpose: string | null; status: string; has_photo: boolean; active: boolean }
interface MyData {
  data: {
    visitor: { name: string | null; company: string | null; first_seen: string | null } | null;
    visits: Visit[];
    invitations: { title: string | null; from: string; status: string }[];
    consents: { notice_version: number; accepted_at: string }[];
    messages: unknown[];
  };
  open_request: { created_at: string } | null;
}

const input = "h-12 w-full rounded-xl border border-line-strong bg-surface px-4 text-base outline-none focus:border-brand focus:ring-2 focus:ring-brand/20";

export default function PrivacyPortal() {
  const { slug = "" } = useParams();
  const { t, i18n } = useMoreT();
  const key = `privacy:${slug}`;
  const [info, setInfo] = useState<PageInfo | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [token, setToken] = useState<string | null>(() => store.get(key));
  const [mine, setMine] = useState<MyData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    pub<PageInfo>(`/privacy/${slug}`).then(setInfo, () => setNotFound(true));
  }, [slug]);

  useEffect(() => {
    if (!token) return;
    pub<MyData>(`/privacy/${slug}/me`, { token }).then(setMine, (e) => {
      if (e instanceof ApiError && e.status === 401) {
        store.set(key, null);
        setToken(null);
        setError(t("privacy.expired"));
      } else setError(errorText(e));
    });
  }, [token, slug, key, t]);

  if (notFound) return <PublicShell><Panel><p>{t("errors.gate_not_found")}</p></Panel></PublicShell>;
  if (!info) return <Spinner />;
  const org = info.org_name;
  const notice = info.notices[i18n.language] ?? info.notices.en;

  return (
    <PublicShell org={org} sub={t("privacy.title")} color={info.primary_color} logo={info.logo_url}>
      <div className="space-y-4">
        <Panel>
          <h1 className="text-xl font-semibold">{t("privacy.title")}</h1>
          <p className="mt-2 text-sm leading-relaxed text-ink-2">{t("privacy.intro", { org, days: info.retention_days })}</p>
          {info.privacy_contact && <p className="mt-2 text-sm text-ink-2">{t("privacy.contact", { contact: info.privacy_contact })}</p>}
          {notice && (
            <details className="mt-3 text-sm">
              <summary className="cursor-pointer font-medium text-brand">{t("privacy.readNotice")}</summary>
              <p className="mt-2 whitespace-pre-line leading-relaxed text-ink-2"><Linkified text={notice} /></p>
            </details>
          )}
        </Panel>
        {error && <p className="rounded-xl bg-bad-50 px-4 py-3 text-sm text-bad" role="alert">{error}</p>}
        {info.self_serve === false ? (
          <Panel>
            <p className="text-sm leading-relaxed text-ink-2" data-testid="privacy-no-self-serve">
              {info.privacy_contact ? t("privacy.askContact", { org, contact: info.privacy_contact }) : t("privacy.askOrg", { org })}
            </p>
          </Panel>
        ) : !token ? (
          <Verify slug={slug} onToken={(tok) => { store.set(key, tok); setError(null); setToken(tok); }} />
        ) : !mine ? <Spinner /> : (
          <Mine slug={slug} token={token} org={org} mine={mine} onChange={setMine}
            onDone={() => { store.set(key, null); setToken(null); setMine(null); }} />
        )}
      </div>
    </PublicShell>
  );
}

function Verify({ slug, onToken }: { slug: string; onToken: (t: string) => void }) {
  const { t, i18n } = useMoreT();
  const [phone, setPhone] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const send = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const r = await pub<{ sent_to: string }>(`/privacy/${slug}/otp/send`, { body: { phone, locale: i18n.language === "hi" ? "hi" : "en" } });
      setSentTo(r.sent_to);
    });
  };
  const verify = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const r = await pub<{ token: string }>(`/privacy/${slug}/otp/verify`, { body: { phone, code } });
      onToken(r.token);
    });
  };
  return (
    <Panel>
      <h2 className="text-lg font-semibold">{t("privacy.verifyTitle")}</h2>
      {!sentTo ? (
        <form onSubmit={send} className="mt-3 space-y-3">
          <p className="text-sm text-ink-2">{t("privacy.verifyHint")}</p>
          <label className="block text-sm font-medium" htmlFor="pp-phone">{t("phone.label")}</label>
          <input id="pp-phone" className={input} type="tel" inputMode="tel" autoComplete="tel" required placeholder="98765 43210" value={phone} onChange={(e) => setPhone(e.target.value)} />
          {error && <p className="text-sm text-bad" role="alert">{error}</p>}
          <BigButton type="submit" busy={busy}>{t("phone.send")}</BigButton>
        </form>
      ) : (
        <form onSubmit={verify} className="mt-3 space-y-3">
          <p className="text-sm text-ink-2">{t("privacy.sentTo", { phone: sentTo })}</p>
          <label className="block text-sm font-medium" htmlFor="pp-code">{t("otp.label")}</label>
          <input id="pp-code" className={`${input} tracking-[0.4em]`} inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} autoFocus />
          {error && <p className="text-sm text-bad" role="alert">{error}</p>}
          <BigButton type="submit" busy={busy}>{t("privacy.show")}</BigButton>
          <button type="button" className="w-full text-sm text-ink-2" onClick={() => { setSentTo(null); setCode(""); }}>{t("otp.change")}</button>
        </form>
      )}
    </Panel>
  );
}

function Mine({ slug, token, org, mine, onChange, onDone }: { slug: string; token: string; org: string; mine: MyData; onChange: (m: MyData) => void; onDone: () => void }) {
  const { t, i18n } = useMoreT();
  const [confirming, setConfirming] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState<"zip" | "erase" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const d = mine.data;
  const date = (s: string) => new Date(s.includes("T") ? s : s.replace(" ", "T") + "+05:30").toLocaleDateString(i18n.language === "hi" ? "hi-IN" : "en-IN", { day: "numeric", month: "short", year: "numeric" });
  const empty = !d.visitor && !d.visits.length && !d.invitations.length;
  const active = d.visits.some((v) => v.active);

  async function download() {
    setBusy("zip");
    setError(null);
    try {
      const res = await fetch(`/api/v1/public/privacy/${slug}/me/export`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new ApiError(res.status, (await res.json().catch(() => null))?.error?.code ?? "error", "Download failed");
      const url = URL.createObjectURL(await res.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = /filename="([^"]+)"/.exec(res.headers.get("content-disposition") ?? "")?.[1] ?? "my-visitor-data.zip";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 30_000);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }
  async function erase() {
    setBusy("erase");
    setError(null);
    try {
      const r = await pub<{ created_at: string }>(`/privacy/${slug}/me/erasure`, { token, body: { reason: reason || null, locale: i18n.language === "hi" ? "hi" : "en" } });
      onChange({ ...mine, open_request: r });
      setConfirming(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  if (empty) {
    return <Panel><p className="text-sm">{t("privacy.nothing", { org })}</p><BigButton className="mt-4" onClick={onDone}>{t("privacy.done")}</BigButton></Panel>;
  }
  return (
    <>
      <Panel>
        <h2 className="text-lg font-semibold">{t("privacy.details")}</h2>
        {d.visitor && (
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="text-ink-3">{t("details.name")}</dt><dd>{d.visitor.name ?? "—"}</dd>
            <dt className="text-ink-3">{t("privacy.company")}</dt><dd>{d.visitor.company ?? "—"}</dd>
            {d.visitor.first_seen && <><dt className="text-ink-3">{t("privacy.firstSeen")}</dt><dd>{date(d.visitor.first_seen)}</dd></>}
          </dl>
        )}
        <h3 className="mt-5 text-sm font-semibold">{t("privacy.visits")} ({d.visits.length})</h3>
        {d.visits.length ? (
          <ul className="mt-2 divide-y divide-line text-sm">
            {d.visits.slice(0, 20).map((v) => (
              <li key={v.id} className="py-2">
                <span className="font-medium">{date(v.requested_at)}</span> · {v.site ?? ""}{v.host ? ` · ${v.host}` : ""}
                <span className="block text-xs text-ink-3">{t(`respond.statusNames.${v.status}`, { defaultValue: v.status })}{v.has_photo ? ` · ${t("privacy.photo")}` : ""}</span>
              </li>
            ))}
          </ul>
        ) : <p className="mt-1 text-sm text-ink-2">{t("privacy.noVisits")}</p>}
        <ul className="mt-4 space-y-1 text-sm text-ink-2">
          {d.invitations.length > 0 && <li>{t("privacy.invitations")}: {d.invitations.length}</li>}
          {d.consents.length > 0 && <li>{t("privacy.consents")}: {d.consents.map((c) => t("privacy.consentLine", { v: c.notice_version, date: date(c.accepted_at) })).join("; ")}</li>}
          <li>{t("privacy.messages")}: {d.messages.length}</li>
        </ul>
      </Panel>
      {error && <p className="rounded-xl bg-bad-50 px-4 py-3 text-sm text-bad" role="alert">{error}</p>}
      <Panel>
        <BigButton onClick={() => void download()} busy={busy === "zip"}>{t("privacy.download")}</BigButton>
        <p className="mt-2 text-center text-xs text-ink-3">{t("privacy.downloadHint")}</p>
        <div className="mt-5 border-t border-line pt-4">
          {mine.open_request ? (
            <div className="text-sm" role="status">
              <p className="font-medium">{t("privacy.requested", { date: date(mine.open_request.created_at) })}</p>
              <p className="mt-1 text-ink-2">{t("privacy.requestedText", { org })}</p>
            </div>
          ) : active ? (
            <p className="text-sm text-ink-2">{t("privacy.activeVisit")}</p>
          ) : !confirming ? (
            <button className="h-12 w-full rounded-xl border border-bad/30 text-base font-medium text-bad hover:bg-bad-50" onClick={() => setConfirming(true)}>{t("privacy.erase")}</button>
          ) : (
            <div className="space-y-3">
              <p className="font-semibold">{t("privacy.eraseTitle")}</p>
              <p className="text-sm text-ink-2">{t("privacy.eraseText", { org })}</p>
              <label className="block text-sm font-medium" htmlFor="pp-reason">{t("privacy.reason")}</label>
              <textarea id="pp-reason" rows={2} maxLength={500} className="w-full rounded-xl border border-line-strong bg-surface px-4 py-2 text-base" value={reason} onChange={(e) => setReason(e.target.value)} />
              <button className="h-12 w-full rounded-xl bg-bad text-base font-medium text-white disabled:opacity-50" disabled={busy === "erase"} onClick={() => void erase()}>{t("privacy.send")}</button>
              <button className="w-full text-sm text-ink-2" onClick={() => setConfirming(false)}>{t("privacy.cancel")}</button>
            </div>
          )}
        </div>
      </Panel>
      <button className="w-full text-sm text-ink-2" onClick={onDone}>{t("privacy.done")}</button>
    </>
  );
}
