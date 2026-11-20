import { useState } from "react";
import { useParams } from "react-router";
import { Alert, Input, Spinner } from "@/components/ui";
import { formatIST, formatPhone } from "@/lib/time";
import { BigButton, Panel, PublicShell } from "./PublicShell";
import { errorText, useMoreT } from "./i18n";
import { pub, type VisitForHost } from "./publicApi";
import { setLoaded, useLoad } from "./useLoad";

/** Opened from the host's WhatsApp message: see the visitor's photo and details, answer. */
export default function RespondPage() {
  const { token = "" } = useParams();
  const { t, i18n } = useMoreT();
  const key = `respond:${token}`;
  const q = useLoad(key, () => pub<VisitForHost>(`/respond/${token}`));
  const [mode, setMode] = useState<null | "wait" | "reject">(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  async function act(action: "approve" | "wait" | "reject") {
    setBusy(true);
    setError(null);
    try {
      const v = await pub<VisitForHost>(`/respond/${token}`, { body: { action, message: message.trim() || null } });
      setLoaded(key, v);
      setDone(v.status);
      setMode(null);
    } catch (e) {
      setError(errorText(e));
      void q.refetch();
    } finally {
      setBusy(false);
    }
  }

  if (q.isLoading) return <PublicShell><Spinner /></PublicShell>;
  if (q.error || !q.data) return <PublicShell><Panel><p>{errorText(q.error)}</p></Panel></PublicShell>;
  const v = q.data;
  const rows: [string, string | null][] = [
    [t("respond.company"), v.visitor_company],
    [t("respond.phone"), formatPhone(v.visitor_phone)],
    [t("respond.purpose"), v.purpose_i18n?.[i18n.language] || v.purpose],
    [t("respond.note"), v.purpose_note],
    [t("respond.people"), v.accompanying_count ? `+${v.accompanying_count}` : null],
    [t("respond.vehicle"), v.vehicle_number],
    [t("respond.id"), v.id_type ? `${t(`idTypes.${v.id_type}`)} ••••${v.id_last4}` : null],
    [t("respond.where"), [v.site_name, v.gate_name].filter(Boolean).join(" · ")],
    [t("respond.when"), formatIST(v.requested_at)],
  ];
  return (
    <PublicShell org={t("respond.title")} sub={v.host_name}>
      <div className="space-y-4">
        {error && <Alert>{error}</Alert>}
        {done && <Alert tone="ok">{t(`respond.done.${done}`)}</Alert>}
        <Panel>
          <div className="flex items-center gap-4">
            {v.photo_url ? <img src={v.photo_url} alt="" className="size-24 shrink-0 rounded-xl object-cover ring-1 ring-line" />
              : <div className="size-24 shrink-0 rounded-xl bg-paper ring-1 ring-line" />}
            <p className="text-xl font-semibold">{v.visitor_name}</p>
          </div>
          <dl className="mt-4 divide-y divide-line text-sm">
            {rows.filter(([, val]) => val).map(([k, val]) => (
              <div key={k} className="flex gap-3 py-2"><dt className="w-28 shrink-0 text-ink-3">{k}</dt><dd>{val}</dd></div>
            ))}
            {Object.entries(v.custom_values).map(([k, val]) => (
              <div key={k} className="flex gap-3 py-2"><dt className="w-28 shrink-0 text-ink-3">{k}</dt>
                <dd>{typeof val === "object" && val ? "✓ " + String((val as { text?: string }).text ?? "") : String(val)}</dd></div>
            ))}
          </dl>
        </Panel>
        {v.can_respond ? (
          mode ? (
            <Panel>
              <label className="block text-sm font-medium" htmlFor="msg">{t("respond.messageLabel")}</label>
              <Input id="msg" className="mt-1.5 h-12 text-base" value={message} maxLength={300} autoFocus
                placeholder={mode === "wait" ? t("respond.waitPlaceholder") : ""} onChange={(e) => setMessage(e.target.value)} />
              <div className="mt-4 grid grid-cols-2 gap-3">
                <button className="h-12 rounded-xl border border-line-strong" onClick={() => setMode(null)}>{t("back")}</button>
                <BigButton busy={busy} className={mode === "reject" ? "!bg-bad" : ""} onClick={() => void act(mode)}>{t(`respond.${mode}`)}</BigButton>
              </div>
            </Panel>
          ) : (
            <div className="space-y-3">
              <BigButton busy={busy} className="!bg-ok" onClick={() => void act("approve")}>{t("respond.approve")}</BigButton>
              <div className="grid grid-cols-2 gap-3">
                <button className="h-12 rounded-xl border border-line-strong bg-surface font-medium" onClick={() => setMode("wait")}>{t("respond.wait")}</button>
                <button className="h-12 rounded-xl border border-bad/40 bg-surface font-medium text-bad" onClick={() => setMode("reject")}>{t("respond.reject")}</button>
              </div>
            </div>
          )
        ) : (
          !done && <p className="rounded-lg bg-paper p-3 text-sm text-ink-2" data-testid="respond-closed">{t("respond.closed", { status: t(`respond.statusNames.${v.status}`) })}</p>
        )}
      </div>
    </PublicShell>
  );
}
