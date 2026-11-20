import { useEffect, useRef, useState, type FormEvent } from "react";
import { Alert, Badge, Button, Field, Input, cx } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { startScanner, type Scanner } from "@/lib/scanner";
import { errText, useS } from "../staff/i18n";
import { guestWindow } from "./QueuePanel";
import { useOnline, useOutbox, type GuardCard, type ScanOut } from "./guardApi";
import { checkOffline, usePack, type OfflineResult } from "./offlinePass";
import { ActionMessages, CardActions, CardFacts, Photo, StatusBadge, type Actions } from "./VisitorCard";

const GOOD = new Set(["ok", "inside"]);

function ResultSheet({ r, actions, onNext }: { r: ScanOut; actions: Actions; onNext: () => void }) {
  const { t } = useS();
  // Follow the visit as the guard acts on it (check in → inside).
  const [card, setCard] = useState<GuardCard | null>(r.visit);
  useEffect(() => setCard(r.visit), [r]);
  const good = GOOD.has(r.result) && card?.alert?.action !== "block";
  const warn = !good && (r.result === "not_approved" || r.result === "not_yet" || r.result === "outside_hours");
  const name = card?.visitor_name ?? r.guest?.name;
  const wrapped: Actions = {
    ...actions,
    checkIn: async (c, reason) => {
      const out = await actions.checkIn(c, reason);
      if (out) setCard({ ...c, status: "checked_in", checked_in_at: new Date().toISOString() });
      return out;
    },
    checkOut: async (c) => {
      const out = await actions.checkOut(c);
      if (out) setCard({ ...c, status: "checked_out", checked_out_at: new Date().toISOString() });
      return out;
    },
  };
  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm" data-testid="scan-result" data-result={r.result}>
      <div className={cx("px-5 py-4 text-center text-lg font-bold", good ? "bg-ok text-white" : warn ? "bg-warn-50 text-warn" : "bg-bad text-white")} role="status">
        {card?.status === "checked_in" && r.result === "ok"
          ? `✓ ${t("guard.result.checkedIn")}`
          : card?.status === "checked_out"
            ? `✓ ${t("guard.result.checkedOut")}`
            : t(`guard.result.${r.result}`)}
      </div>
      <div className="space-y-4 p-5">
        {r.result === "wrong_site" && r.site_name && <p className="text-center font-medium">{t("guard.result.wrongSiteIs", { site: r.site_name })}</p>}
        {r.result === "blocked" && <p className="text-center font-medium text-bad">{t("guard.result.blockedHelp")}</p>}
        {r.result === "not_approved" && <p className="text-center text-sm text-ink-2">{t("guard.result.pendingHelp")}</p>}
        {name && (
          <div className="flex items-center gap-4">
            <Photo url={card?.photo_url ?? null} size="lg" />
            <div className="min-w-0 space-y-1">
              <p className="text-xl font-semibold">{name}</p>
              {(card?.visitor_company ?? r.guest?.company) && <p className="text-ink-2">{card?.visitor_company ?? r.guest?.company}</p>}
              <div className="flex flex-wrap gap-1.5">
                {card && <StatusBadge status={card.status} />}
                {(card?.source === "invite" || r.guest) && <Badge tone="brand">{t("guard.card.invite")}</Badge>}
              </div>
            </div>
          </div>
        )}
        {card?.alert && (
          <Alert tone={card.alert.action === "block" ? "bad" : "warn"}>{t("guard.card.alert")}: {card.alert.reason}</Alert>
        )}
        {card && <CardFacts card={card} />}
        {!card && r.guest && (
          <p className="text-sm text-ink-2">{r.guest.host_name} · {guestWindow(r.guest, t)}</p>
        )}
        {(card?.invite_notes ?? r.guest?.notes) && <p className="rounded-lg bg-paper p-3 text-sm">📝 {card?.invite_notes ?? r.guest?.notes}</p>}
        <ActionMessages actions={actions} />
        {card && card.status !== "checked_out" && <CardActions card={card} actions={wrapped} big />}
        <Button variant="secondary" size="lg" className="w-full" onClick={onNext}>{t("guard.scan.next")}</Button>
      </div>
    </div>
  );
}

/** A pass checked on this phone because the server couldn't be reached. */
function OfflineSheet({ o, siteId, actions, updatedAt, onNext }: {
  o: { res: OfflineResult; token: string };
  siteId: string;
  actions: Actions;
  updatedAt: string;
  onNext: () => void;
}) {
  const { t } = useS();
  const [saved, setSaved] = useState<"in" | "out" | null>(null);
  const { pending } = useOutbox();
  const { res, token } = o;
  const e = res.entry;
  const queueId = e ? (e.kind === "visit" || saved === "out" ? e.ref_id : `guest:${e.ref_id}`) : "";
  const waiting = pending.some((p) => p.visitId === queueId);
  const good = res.status === "ok" || res.status === "inside";
  const warn = res.status === "unknown" || res.status === "not_yet" || res.status === "outside_hours" || res.status === "no_consent";
  const head = saved
    ? waiting
      ? t(saved === "in" ? "guard.offlinePass.savedIn" : "guard.offlinePass.savedOut")
      : t(saved === "in" ? "guard.result.checkedIn" : "guard.result.checkedOut")
    : t(`guard.offlinePass.result.${res.status}`);

  async function checkIn() {
    if (!e) return;
    const r = await actions.submit(e.kind === "visit" ? e.ref_id : `guest:${e.ref_id}`, "pass-check-in", e.name, { site_id: siteId, payload: token });
    if (r) setSaved("in");
  }
  async function checkOut() {
    if (!e) return;
    const r = await actions.submit(e.ref_id, "check-out", e.name);
    if (r) setSaved("out");
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface shadow-sm" data-testid="offline-result" data-result={res.status}>
      <div className={cx("px-5 py-4 text-center text-lg font-bold", saved || good ? "bg-ok text-white" : warn ? "bg-warn-50 text-warn" : "bg-bad text-white")} role="status">
        {saved ? `✓ ${head}` : head}
      </div>
      <div className="space-y-4 p-5">
        <p className="rounded-lg bg-paper p-3 text-sm text-ink-2">{t("guard.offlinePass.note", { time: updatedAt })}</p>
        {e && (
          <div className="flex items-center gap-4">
            <Photo url={e.photo_url} size="lg" />
            <div className="min-w-0 space-y-1">
              <p className="text-xl font-semibold">{e.name}</p>
              {e.company && <p className="text-ink-2">{e.company}</p>}
              <p className="text-sm text-ink-2">{t("guard.offlinePass.meeting", { host: e.host_name })}{e.purpose ? ` · ${e.purpose}` : ""}</p>
              {e.kind === "invite" && <Badge tone="brand">{t("guard.card.invite")}</Badge>}
            </div>
          </div>
        )}
        {e?.alert && <Alert tone={e.alert.action === "block" ? "bad" : "warn"}>{t("guard.card.alert")}: {e.alert.reason}</Alert>}
        {res.status === "unknown" && <p className="text-sm">{t("guard.offlinePass.unknownHelp")}</p>}
        {res.status === "no_consent" && <p className="text-sm">{t("guard.offlinePass.noConsentHelp")}</p>}
        {res.status === "blocked" && <p className="text-center font-medium text-bad">{t("guard.result.blockedHelp")}</p>}
        {(!saved || waiting) && <ActionMessages actions={actions} />}
        {!saved && res.status === "ok" && (
          <Button size="lg" className="w-full" busy={!!actions.busy} onClick={() => void checkIn()} data-testid="offline-check-in">
            {t("guard.offlinePass.checkIn")}
          </Button>
        )}
        {!saved && res.status === "inside" && e?.kind === "visit" && (
          <Button size="lg" variant="secondary" className="w-full" busy={!!actions.busy} onClick={() => void checkOut()}>
            {t("guard.offlinePass.checkOut")}
          </Button>
        )}
        <Button variant="secondary" size="lg" className="w-full" onClick={onNext}>{t("guard.scan.next")}</Button>
      </div>
    </div>
  );
}

export function ScanPanel({ siteId, actions }: { siteId: string; actions: Actions }) {
  const { t } = useS();
  const online = useOnline();
  const video = useRef<HTMLVideoElement>(null);
  const scanner = useRef<Scanner | null>(null);
  const [camera, setCamera] = useState<"off" | "starting" | "on" | "error">("off");
  const [manual, setManual] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScanOut | null>(null);
  const [offline, setOffline] = useState<{ res: OfflineResult; token: string } | null>(null);
  const pack = usePack(siteId);
  const handling = useRef(false);
  const updatedAt = pack ? new Date(pack.generated_at).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit" }) : "";

  /** The server can't be reached: check the pass on this phone instead. */
  async function checkHere(payload: string) {
    const res = await checkOffline(payload, pack!);
    setOffline({ res, token: payload.trim() });
    stop();
    navigator.vibrate?.(res.status === "ok" || res.status === "inside" ? 60 : [80, 60, 80]);
  }

  async function check(payload: string) {
    if (handling.current || !payload.trim()) return;
    handling.current = true;
    setBusy(true);
    setError(null);
    actions.clear();
    try {
      if (!navigator.onLine && pack) {
        await checkHere(payload);
        return;
      }
      const r = await api<ScanOut>("/guard/scan", { method: "POST", body: { site_id: siteId, payload: payload.trim() } });
      setResult(r);
      stop();
      navigator.vibrate?.(GOOD.has(r.result) ? 60 : [80, 60, 80]);
    } catch (e) {
      // No answer from the API (network down, or a proxy/gateway error instead of our
      // JSON error): fall back. A real answer, even an error, is shown as it is.
      const unreachable = !(e instanceof ApiError) || e.code === "server_unavailable" || e.status >= 502;
      if (unreachable && pack) await checkHere(payload);
      else setError(errText(e));
    } finally {
      setBusy(false);
      handling.current = false;
    }
  }

  async function start() {
    if (!video.current) return;
    setCamera("starting");
    try {
      scanner.current = await startScanner(video.current, (text) => void check(text));
      setCamera("on");
    } catch {
      setCamera("error");
    }
  }
  function stop() {
    scanner.current?.stop();
    scanner.current = null;
    setCamera((c) => (c === "error" ? c : "off"));
  }
  useEffect(() => () => scanner.current?.stop(), []);

  function submitManual(e: FormEvent) {
    e.preventDefault();
    void check(manual).then(() => setManual(""));
  }

  if (offline) {
    return <OfflineSheet o={offline} siteId={siteId} actions={actions} updatedAt={updatedAt} onNext={() => { setOffline(null); actions.clear(); void start(); }} />;
  }
  if (result) {
    return <ResultSheet r={result} actions={actions} onNext={() => { setResult(null); actions.clear(); void start(); }} />;
  }

  return (
    <div className="space-y-4">
      {!online && <Alert tone="warn">{pack ? t("guard.offlinePass.banner", { time: updatedAt, count: pack.entries.length }) : t("guard.scan.offline")}</Alert>}
      <div className="relative aspect-square w-full overflow-hidden rounded-2xl bg-ink">
        <video ref={video} className={cx("size-full object-cover", camera !== "on" && "invisible")} muted playsInline />
        {camera === "on" && (
          <div className="pointer-events-none absolute inset-[14%] rounded-2xl border-4 border-white/80 shadow-[0_0_0_9999px_rgba(0,0,0,0.35)]" />
        )}
        {camera !== "on" && (
          <div className="absolute inset-0 grid place-items-center p-6 text-center">
            <div className="space-y-3">
              <p className="text-sm text-white/80">{camera === "error" ? t(window.isSecureContext ? "guard.scan.cameraError" : "guard.scan.cameraInsecure") : t("guard.scan.hint")}</p>
              <Button size="lg" onClick={() => void start()} busy={camera === "starting"}>{t("guard.scan.start")}</Button>
            </div>
          </div>
        )}
        {busy && <div className="absolute inset-x-0 bottom-0 bg-ink/70 py-2 text-center text-sm text-white">{t("common.loading")}…</div>}
      </div>
      {camera === "on" && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-ink-2">{t("guard.scan.hint")}</p>
          <Button variant="ghost" size="sm" onClick={stop}>{t("guard.scan.stop")}</Button>
        </div>
      )}
      {error && <Alert>{error}</Alert>}
      <form onSubmit={submitManual} className="space-y-2">
        <Field label={t("guard.scan.manual")} hint={t("guard.scan.manualHint")}>
          {(id) => (
            <div className="flex gap-2">
              <Input id={id} value={manual} onChange={(e) => setManual(e.target.value)} autoComplete="off" autoCapitalize="off" spellCheck={false} data-testid="scan-manual" />
              <Button type="submit" className="shrink-0 whitespace-nowrap" busy={busy} disabled={!manual.trim()}>{t("guard.scan.check")}</Button>
            </div>
          )}
        </Field>
      </form>
    </div>
  );
}
