import { useEffect, useState } from "react";
import { useParams, useSearchParams } from "react-router";
import { Alert, Spinner, cx } from "@/components/ui";
import { subscribe } from "@/lib/sse";
import { PassCard } from "./PassCard";
import { Panel, PublicShell } from "./PublicShell";
import { errorText, useT } from "./i18n";
import { pub, store, type VisitStatus } from "./publicApi";
import { setLoaded, useLoad } from "./useLoad";

const LIVE = new Set(["pending", "waiting", "approved"]);

export default function VisitStatusPage() {
  const { visitId = "" } = useParams();
  const [params] = useSearchParams();
  const token = params.get("t") ?? store.get(`vms.visit.${visitId}`);
  const { t } = useT();
  const key = `visit:${visitId}`;
  const q = useLoad(key, () => pub<VisitStatus>(`/visits/${visitId}`, { token }), {
    enabled: !!token,
    // Safety net behind the live stream (flaky mobile networks, proxies that buffer SSE).
    refetchInterval: (data) => (data && !LIVE.has(data.status) ? false : 10_000),
  });
  const status = q.data?.status;

  useEffect(() => {
    if (!token || (status && !LIVE.has(status))) return;
    return subscribe(`/api/v1/public/visits/${visitId}/events`, token, (event, data) => {
      if (event === "status") setLoaded(key, JSON.parse(data) as VisitStatus);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, visitId, status === undefined || LIVE.has(status)]);

  if (!token) return <PublicShell><Panel><p>{t("status.lost")}</p></Panel></PublicShell>;
  if (q.isLoading) return <PublicShell><Spinner /></PublicShell>;
  if (q.error || !q.data) return <PublicShell><Panel><p>{q.error ? errorText(q.error) : t("status.lost")}</p></Panel></PublicShell>;
  return (
    <PublicShell org={q.data.site_name} sub={q.data.gate_name ?? undefined}>
      <StatusView v={q.data} token={token} onChange={(v) => setLoaded(key, v)} />
    </PublicShell>
  );
}

function StatusView({ v, token, onChange }: { v: VisitStatus; token: string; onChange: (v: VisitStatus) => void }) {
  const { t } = useT();
  const [error, setError] = useState<string | null>(null);
  const host = v.host_name;
  const tone = v.status === "approved" || v.status === "checked_in" ? "ok" : v.status === "pending" || v.status === "waiting" ? "wait" : "bad";

  async function cancel() {
    if (!confirm(t("status.cancelConfirm"))) return;
    try {
      onChange(await pub<VisitStatus>(`/visits/${v.id}/cancel`, { token, method: "POST" }));
    } catch (e) {
      setError(errorText(e));
    }
  }

  return (
    <div className="space-y-4" aria-live="polite">
      {error && <Alert>{error}</Alert>}
      <Panel>
        <div className="flex items-start gap-4">
          <StatusIcon tone={tone} />
          <div className="min-w-0">
            <h1 className="text-xl font-semibold" data-testid="visit-status" data-status={v.status}>{t(`status.${v.status}`, { host })}</h1>
            {["pending", "waiting", "approved", "rejected", "expired"].includes(v.status) && (
              <p className="mt-1 text-sm text-ink-2">
                {t(v.whatsapp === false && (v.status === "pending" || v.status === "approved") ? `status.${v.status}HelpScreen` : `status.${v.status}Help`, { host })}
              </p>
            )}
          </div>
        </div>
        {v.status === "pending" && v.escalated && <p className="mt-4 rounded-lg bg-warn-50 p-3 text-sm text-warn">{t("status.escalated", { host })}</p>}
        {v.host_message && (
          <blockquote className="mt-4 rounded-lg bg-paper p-3 text-sm">
            <p className="text-xs text-ink-3">{t("status.message", { host })}</p>
            <p className="mt-0.5">“{v.host_message}”</p>
          </blockquote>
        )}
        {(v.status === "pending" || v.status === "waiting") && (
          <div className="mt-5 flex flex-wrap items-center justify-between gap-x-4 gap-y-2 text-sm">
            <span className="flex items-center gap-2 text-ink-3"><span className="size-2 animate-pulse rounded-full bg-ok" />{t("status.live")}</span>
            <button className="text-bad" onClick={() => void cancel()}>{t("status.cancel")}</button>
          </div>
        )}
      </Panel>
      {v.pass && <PassCard token={v.pass.token} />}
      {v.pass && v.whatsapp === false && (
        <p className="text-center text-sm">
          <a className="text-brand underline" href={v.pass.url} target="_blank" rel="noreferrer">{t("status.openPass")}</a>
        </p>
      )}
    </div>
  );
}

function StatusIcon({ tone }: { tone: "ok" | "wait" | "bad" }) {
  return (
    <span className={cx("flex size-11 shrink-0 items-center justify-center rounded-full",
      tone === "ok" ? "bg-ok-50 text-ok" : tone === "wait" ? "bg-warn-50 text-warn" : "bg-bad-50 text-bad")} aria-hidden>
      {tone === "ok" ? (
        <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M5 12.5 10 17 19 7" /></svg>
      ) : tone === "wait" ? (
        <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" /></svg>
      ) : (
        <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2.5"><path d="M7 7l10 10M17 7 7 17" /></svg>
      )}
    </span>
  );
}
