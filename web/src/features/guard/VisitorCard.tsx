import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { Alert, Badge, Button, Dialog, Field, Input, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { newKey, type ActionKind } from "@/lib/offlineQueue";
import { clock, errText, useS } from "../staff/i18n";
import { gk, outbox, type GuardCard } from "./guardApi";

export function Photo({ url, size = "md" }: { url: string | null; size?: "md" | "lg" }) {
  const cls = size === "lg" ? "size-28 rounded-2xl" : "size-14 rounded-xl";
  return url ? (
    <img src={url} alt="" className={cx(cls, "shrink-0 object-cover ring-1 ring-line")} />
  ) : (
    <div className={cx(cls, "grid shrink-0 place-items-center bg-paper text-ink-3 ring-1 ring-line")} aria-hidden>
      <svg viewBox="0 0 24 24" className="size-1/2" fill="currentColor"><path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm0 2c-4.4 0-8 2.2-8 5v1h16v-1c0-2.8-3.6-5-8-5Z" /></svg>
    </div>
  );
}

const TONE: Record<string, "ok" | "warn" | "bad" | "neutral" | "brand"> = {
  pending: "warn",
  waiting: "warn",
  approved: "ok",
  checked_in: "brand",
  checked_out: "neutral",
  rejected: "bad",
  expired: "neutral",
  cancelled: "neutral",
};

export function StatusBadge({ status }: { status: string }) {
  const { t } = useS();
  return <Badge tone={TONE[status] ?? "neutral"}>{t(`host.statuses.${status}`, { defaultValue: status })}</Badge>;
}

/** Check-in / check-out go through the offline outbox; the rest need the network. */
export function useGuardActions(siteId: string) {
  const qc = useQueryClient();
  const { t } = useS();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const refresh = () => qc.invalidateQueries({ queryKey: gk.queue(siteId) });

  async function run(id: string, fn: () => Promise<unknown>) {
    setBusy(id);
    setError(null);
    setNote(null);
    try {
      return await fn();
    } catch (e) {
      setError(errText(e));
      return undefined;
    } finally {
      setBusy(null);
      void refresh();
    }
  }

  /** Through the outbox: sent now if possible, otherwise saved and sent later. */
  const submit = (visitId: string, kind: ActionKind, label: string, body: Record<string, unknown> = {}) =>
    run(`${visitId}:${kind}`, async () => {
      const r = await outbox.submit({ id: newKey(), visitId, kind, label, occurredAt: new Date().toISOString(), body });
      if (r === null) setNote(t("guard.actions.queued"));
      return r ?? true;
    });
  const move = (c: GuardCard, kind: ActionKind, body: Record<string, unknown> = {}) => submit(c.id, kind, c.visitor_name ?? "", body);

  return {
    busy,
    error,
    note,
    clear: () => {
      setError(null);
      setNote(null);
    },
    checkIn: (c: GuardCard, overrideReason?: string) =>
      move(c, "check-in", overrideReason ? { override_reason: overrideReason } : {}),
    checkOut: (c: GuardCard) => move(c, "check-out"),
    submit,
    remind: (c: GuardCard) =>
      run(`${c.id}:remind`, async () => {
        await api(`/guard/visits/${c.id}/notify-host`, { method: "POST" });
        setNote(t("guard.actions.reminded"));
        return true;
      }),
  };
}

export type Actions = ReturnType<typeof useGuardActions>;

export function AdmitDialog({ card, open, onClose, onAdmit, busy }: {
  card: GuardCard;
  open: boolean;
  onClose: () => void;
  onAdmit: (reason: string) => void;
  busy: boolean;
}) {
  const { t } = useS();
  const [reason, setReason] = useState("");
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={t("guard.actions.admitTitle")}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button>
          <Button busy={busy} disabled={reason.trim().length < 3} onClick={() => onAdmit(reason.trim())}>
            {t("guard.actions.confirmAdmit")}
          </Button>
        </>
      }
    >
      <p className="mb-3 text-sm text-ink-2">
        <strong className="text-ink">{card.visitor_name}</strong> → {card.host_name}
      </p>
      <p className="mb-4 text-sm text-ink-2">{t("guard.actions.admitHelp")}</p>
      <Field label={t("guard.actions.reason")}>
        {(id) => (
          <Input id={id} value={reason} maxLength={300} placeholder={t("guard.actions.reasonPlaceholder")}
            onChange={(e) => setReason(e.target.value)} />
        )}
      </Field>
    </Dialog>
  );
}

/** Buttons for what a guard can do with this visit right now. */
export function CardActions({ card, actions, syncing, big }: { card: GuardCard; actions: Actions; syncing?: boolean; big?: boolean }) {
  const { t } = useS();
  const [admit, setAdmit] = useState(false);
  const size = big ? "lg" : "md";
  const b = (k: string) => actions.busy === `${card.id}:${k}`;
  if (syncing) return <Badge tone="warn">{t("guard.card.syncing")}</Badge>;
  const blocked = card.alert?.action === "block";
  let out: ReactNode = null;
  if (card.status === "approved" && !blocked) {
    out = <Button size={size} className={big ? "w-full" : ""} busy={b("check-in")} onClick={() => void actions.checkIn(card)}>{t("guard.actions.checkIn")}</Button>;
  } else if (card.status === "checked_in") {
    out = <Button size={size} variant="secondary" className={big ? "w-full" : ""} busy={b("check-out")} onClick={() => void actions.checkOut(card)}>{t("guard.actions.checkOut")}</Button>;
  } else if (card.status === "pending" || card.status === "waiting") {
    out = (
      // Stacked: the usual step (remind) on top, the exception (let in) smaller below it.
      <div className={cx("flex flex-col items-stretch gap-1", big ? "w-full" : "w-full sm:w-44")} data-testid="waiting-actions">
        <Button size={size} variant="secondary" busy={b("remind")} onClick={() => void actions.remind(card)}>{t("guard.actions.remind")}</Button>
        <Button size="sm" variant="ghost" className="text-ink-2" onClick={() => setAdmit(true)}>{t("guard.actions.admit")}</Button>
        <AdmitDialog card={card} open={admit} busy={b("check-in")} onClose={() => setAdmit(false)}
          onAdmit={async (r) => {
            await actions.checkIn(card, r);
            setAdmit(false);
          }} />
      </div>
    );
  }
  return <>{out}</>;
}

export function CardFacts({ card }: { card: GuardCard }) {
  const { t, i18n } = useS();
  const purpose = card.purpose_i18n?.[i18n.language] || card.purpose;
  return (
    <div className="min-w-0 space-y-0.5 text-sm text-ink-2">
      <p className="truncate">
        <span className="text-ink-3">{t("guard.card.visiting")}:</span> <span className="font-medium text-ink">{card.host_name}</span>
      </p>
      {(purpose || card.purpose_note) && (
        <p className="truncate">{[purpose, card.purpose_note].filter(Boolean).join(" · ")}</p>
      )}
      {card.phone_verified === false && card.status !== "checked_out" && (
        <p className="text-xs font-medium text-warn" data-testid="phone-unverified">{t("guard.card.unverified")}</p>
      )}
      <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-ink-3">
        {card.phone_last4 && <span>{t("guard.card.phone", { last4: card.phone_last4 })}</span>}
        {card.accompanying_count > 0 && <span>{t("common.people", { n: card.accompanying_count })}</span>}
        {card.vehicle_number && <span>{t("guard.card.vehicle")}: {card.vehicle_number}</span>}
        {card.id_type && <span>{t("guard.card.id")}: {t(`guard.ids.${card.id_type}`)} ••{card.id_last4}</span>}
        {card.gate_name && <span>{t("common.via", { gate: card.gate_name })}</span>}
      </p>
    </div>
  );
}

function when(card: GuardCard, t: (k: string, o?: Record<string, unknown>) => string): string {
  switch (card.status) {
    case "checked_in":
      return t("guard.card.inSince", { time: clock(card.checked_in_at) });
    case "checked_out":
      return t("guard.card.leftAt", { time: clock(card.checked_out_at) }) + (card.checkout_method === "auto" ? ` (${t("guard.card.autoOut")})` : "");
    case "approved":
      return t("guard.card.approvedAt", { time: clock(card.approved_at) });
    case "pending":
    case "waiting":
      return t("guard.card.waitingSince", { time: clock(card.requested_at) });
    default:
      return clock(card.requested_at);
  }
}

/** One visitor in a queue list. */
export function VisitorRow({ card, actions, syncing }: { card: GuardCard; actions: Actions; syncing?: boolean }) {
  const { t } = useS();
  return (
    <li className="flex flex-wrap items-center gap-3 px-4 py-3 sm:flex-nowrap" data-testid="visitor-row" data-status={card.status}>
      <Photo url={card.photo_url} />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <p className="truncate font-semibold text-ink">{card.visitor_name}</p>
          {card.visitor_company && <span className="truncate text-sm text-ink-3">{card.visitor_company}</span>}
          {card.source === "invite" && <Badge tone="brand">{t("guard.card.invite")}</Badge>}
          {card.alert && <Badge tone={card.alert.action === "block" ? "bad" : "warn"}>{t("guard.card.alert")}: {card.alert.reason}</Badge>}
        </div>
        <CardFacts card={card} />
        <p className="mt-0.5 text-xs text-ink-3">
          {when(card, t)}
          {card.escalated && card.status === "pending" && ` · ${t("guard.card.escalated")}`}
        </p>
        {card.host_message && <p className="mt-1 text-xs text-ink-2">{t("guard.card.hostSays", { msg: card.host_message })}</p>}
        {card.guard_note && <p className="mt-1 text-xs text-ink-2">{t("guard.card.letInBy", { note: card.guard_note })}</p>}
        {card.invite_notes && <p className="mt-1 text-xs text-ink-2">📝 {card.invite_notes}</p>}
      </div>
      <div className={cx("ml-auto shrink-0", (card.status === "pending" || card.status === "waiting") && "w-full sm:w-auto")}>
        <CardActions card={card} actions={actions} syncing={syncing} />
      </div>
    </li>
  );
}

export function ActionMessages({ actions }: { actions: Actions }) {
  if (!actions.error && !actions.note) return null;
  return actions.error ? <Alert>{actions.error}</Alert> : <Alert tone="ok">{actions.note}</Alert>;
}
