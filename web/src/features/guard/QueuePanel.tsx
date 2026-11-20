import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useState, type ReactNode } from "react";
import { Alert, Badge, Button, Checkbox, Dialog, Input, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { openEvacuationPdf } from "@/lib/openPdf";
import { whatsappShareUrl } from "@/lib/share";
import { errText, hhmm, shortDay, useS, clock } from "../staff/i18n";
import { gk, useOutbox, useQueue, withPending, type ExpectedGuest, type GuardCard, type GuardForm, type ScanOut } from "./guardApi";
import { ActionMessages, Photo, VisitorRow, type Actions } from "./VisitorCard";

function Section({ title, count, children, tone }: { title: string; count: number; children: ReactNode; tone?: "bad" }) {
  if (!count) return null;
  return (
    <section className="overflow-hidden rounded-xl border border-line bg-surface">
      <h2 className={`flex items-center justify-between border-b border-line px-4 py-2.5 text-sm font-semibold ${tone === "bad" ? "bg-bad-50 text-bad" : ""}`}>
        {title} <span className="rounded-full bg-ink/5 px-2 text-xs font-medium text-ink-2">{count}</span>
      </h2>
      <ul className="divide-y divide-line">{children}</ul>
    </section>
  );
}

function matches(q: string, ...vals: (string | null | undefined)[]) {
  if (!q) return true;
  const s = q.toLowerCase();
  return vals.some((v) => v?.toLowerCase().includes(s));
}

export function guestWindow(g: ExpectedGuest, t: (k: string, o?: Record<string, unknown>) => string) {
  if (g.kind === "multi_day" && g.daily_start_time) {
    return `${shortDay(g.valid_from)} – ${shortDay(g.valid_until)} · ${t("guard.guest.daily", { from: hhmm(g.daily_start_time), to: hhmm(g.daily_end_time) })}`;
  }
  return t("guard.guest.window", { from: clock(g.valid_from), to: clock(g.valid_until) });
}

/** A pre-approved guest arriving without showing their QR: picked from the list. */
function GuestRow({ g, siteId, actions, notice }: { g: ExpectedGuest; siteId: string; actions: Actions; notice?: GuardForm["notices"][string] }) {
  const { t, i18n } = useS();
  const qc = useQueryClient();
  const [ask, setAsk] = useState(false);
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function arrive(consent: boolean) {
    setBusy(true);
    setErr(null);
    try {
      const r = await api<ScanOut>(`/guard/invite-guests/${g.guest_id}/arrive`, {
        method: "POST",
        body: { site_id: siteId, consent, locale: i18n.language },
      });
      if (r.result === "ok" && r.visit) {
        await actions.checkIn(r.visit);
        setAsk(false);
      } else setErr(t(`guard.result.${r.result}`));
    } catch (e) {
      setErr(errText(e));
    } finally {
      setBusy(false);
      void qc.invalidateQueries({ queryKey: gk.queue(siteId) });
    }
  }

  return (
    <li className="flex flex-wrap items-center gap-3 px-4 py-3 sm:flex-nowrap" data-testid="guest-row">
      <Photo url={null} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2">
          <p className="font-semibold">{g.name}</p>
          {g.company && <span className="text-sm text-ink-3">{g.company}</span>}
          <Badge tone="brand">{t("guard.card.invite")}</Badge>
        </div>
        <p className="text-sm text-ink-2"><span className="text-ink-3">{t("guard.card.visiting")}:</span> <span className="font-medium text-ink">{g.host_name}</span>{g.title && ` · ${g.title}`}</p>
        <p className="text-xs text-ink-3">{guestWindow(g, t)}{g.phone_last4 && ` · ${t("guard.card.phone", { last4: g.phone_last4 })}`}</p>
        {g.notes && <p className="mt-1 text-xs text-ink-2">📝 {g.notes}</p>}
        {err && !ask && <p className="mt-1 text-sm text-bad">{err}</p>}
      </div>
      <Button className="ml-auto" busy={busy && !ask} onClick={() => (g.consented ? void arrive(false) : setAsk(true))}>
        {t("guard.actions.checkIn")}
      </Button>
      <Dialog open={ask} onClose={() => setAsk(false)} title={t("guard.guest.consentTitle")}
        footer={<><Button variant="secondary" onClick={() => setAsk(false)}>{t("common.cancel")}</Button>
          <Button disabled={!agree} busy={busy} onClick={() => void arrive(true)}>{t("guard.actions.checkIn")}</Button></>}>
        <p className="mb-3 text-sm text-ink-2">{t("guard.guest.consentHelp")}</p>
        {notice && <div className="mb-4 max-h-60 overflow-y-auto whitespace-pre-line rounded-lg bg-paper p-3 text-sm text-ink-2">{notice.body}</div>}
        <Checkbox label={t("guard.guest.consentConfirm")} checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        {err && <div className="mt-3"><Alert>{err}</Alert></div>}
      </Dialog>
    </li>
  );
}

/** In an emergency: the list of everyone on site, as a PDF or sent to the site's
 *  safety contacts on WhatsApp. Works from the gate (needs the network). */
function Evacuation({ siteId }: { siteId: string }) {
  const { t } = useS();
  const [busy, setBusy] = useState<"pdf" | "share" | null>(null);
  const whatsapp = useAuth().me?.whatsapp_enabled !== false;
  const [msg, setMsg] = useState<{ ok: boolean; text: string; share?: string } | null>(null);
  async function run(kind: "pdf" | "share") {
    if (kind === "share" && whatsapp && !window.confirm(t("guard.evac.confirm"))) return;
    setBusy(kind);
    setMsg(null);
    try {
      if (kind === "pdf") await openEvacuationPdf(siteId);
      else {
        const r = await api<{ sent: number; people: number; share_text?: string }>("/evacuation/share", { method: "POST", body: { site_id: siteId } });
        setMsg(r.share_text
          ? { ok: true, text: t("guard.evac.ready", { people: r.people }), share: r.share_text }
          : { ok: true, text: t("guard.evac.sent", { n: r.sent, people: r.people }) });
      }
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    } finally {
      setBusy(null);
    }
  }
  return (
    <section className="space-y-2 rounded-xl border border-bad/25 bg-surface p-4" data-testid="evacuation">
      <h2 className="text-sm font-semibold text-bad">{t("guard.evac.title")}</h2>
      <div className="flex flex-wrap gap-2">
        <Button variant="secondary" busy={busy === "pdf"} onClick={() => void run("pdf")}>{t("guard.evac.pdf")}</Button>
        <Button variant="danger" busy={busy === "share"} onClick={() => void run("share")}>{t(whatsapp ? "guard.evac.share" : "guard.evac.shareSelf")}</Button>
      </div>
      {msg && (
        <Alert tone={msg.ok ? "ok" : "bad"}>
          {msg.text}
          {msg.share && <> <a className="font-semibold underline" href={whatsappShareUrl(msg.share)} target="_blank" rel="noreferrer">{t("guard.evac.open")}</a></>}
        </Alert>
      )}
    </section>
  );
}

export function QueuePanel({ siteId, actions, form }: { siteId: string; actions: Actions; form?: GuardForm }) {
  const { t, i18n } = useS();
  const q = useQueue(siteId);
  const { pending } = useOutbox();
  const [filter, setFilter] = useState("");
  const data = useMemo(() => (q.data ? withPending(q.data, pending) : null), [q.data, pending]);
  if (q.isLoading) return <Spinner label={t("common.loading")} />;
  if (q.error || !data) return <Alert>{errText(q.error)}</Alert>;

  const f = (cs: GuardCard[]) => cs.filter((c) => matches(filter, c.visitor_name, c.visitor_company, c.phone_last4, c.host_name, c.vehicle_number));
  const rows = (cs: GuardCard[]) => f(cs).map((c) => <VisitorRow key={c.id} card={c} actions={actions} syncing={data.syncing.has(c.id)} />);
  const guests = data.invites.filter((g) => matches(filter, g.name, g.company, g.phone_last4, g.host_name, g.title));
  const notice = form?.notices[i18n.language] ?? form?.notices.en;
  const total = data.awaiting.length + data.expected.length + data.on_site.length + data.left.length + data.invites.length + data.alerts.length;

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Input type="search" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={t("guard.queue.filter")} aria-label={t("common.search")} />
        <Button variant="secondary" onClick={() => void q.refetch()} aria-label={t("guard.queue.refresh")}>↻</Button>
      </div>
      <ActionMessages actions={actions} />
      {total === 0 && <p className="py-10 text-center text-sm text-ink-3">{t("guard.queue.empty")}</p>}
      <Section title={t("guard.queue.alerts")} count={data.alerts.length} tone="bad">{rows(data.alerts)}</Section>
      <Section title={t("guard.queue.expected")} count={f(data.expected).length}>{rows(data.expected)}</Section>
      <Section title={t("guard.queue.invites")} count={guests.length}>
        {guests.map((g) => <GuestRow key={g.guest_id} g={g} siteId={siteId} actions={actions} notice={notice} />)}
      </Section>
      <Section title={t("guard.queue.awaiting")} count={f(data.awaiting).length}>{rows(data.awaiting)}</Section>
      <Section title={`${t("guard.queue.onSite")} · ${t("guard.peopleOnSite", { count: data.people_on_site })}`} count={f(data.on_site).length}>{rows(data.on_site)}</Section>
      <Section title={t("guard.queue.left")} count={f(data.left).length}>{rows(data.left)}</Section>
      <Evacuation siteId={siteId} />
    </div>
  );
}
