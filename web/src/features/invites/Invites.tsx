import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Alert, Badge, Button, Checkbox, Dialog, Field, Input, Select, Spinner, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { openWhatsApp } from "@/lib/share";
import type { Page } from "@/lib/types";
import { errText, hhmm, shortDay, useS } from "../staff/i18n";

export interface Guest {
  id: string;
  name: string;
  phone: string;
  company: string | null;
  status: "active" | "revoked" | "used";
  use_count: number;
  max_uses: number | null;
  last_used_at: string | null;
  sent_at: string | null;
  consented_at: string | null;
  pass_url: string | null;
  share_text?: string | null; // the invitation, to send from your own WhatsApp
}

export interface Invite {
  id: string;
  site_id: string;
  site_name: string;
  host_id: string;
  host_name: string;
  purpose_id: string | null;
  kind: "single" | "group" | "multi_day";
  title: string | null;
  notes: string | null;
  valid_from: string;
  valid_until: string;
  daily_start_time: string | null;
  daily_end_time: string | null;
  status: "active" | "revoked" | "expired";
  created_at: string;
  guest_count: number;
  arrived_count: number;
  guests: Guest[] | null;
}

interface Opt {
  id: string;
  name: string;
}

const ik = { list: (q: object) => ["invites", q] as const, one: (id: string) => ["invite", id] as const };

const timeFmt = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true });
const timeOf = (iso: string) => timeFmt.format(new Date(iso));

function todayIST() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
}

export function inviteWhen(i: Invite) {
  if (i.kind === "multi_day") {
    return `${shortDay(i.valid_from)} – ${shortDay(i.valid_until)}, ${hhmm(i.daily_start_time)}–${hhmm(i.daily_end_time)}`;
  }
  return `${shortDay(i.valid_from)}, ${timeOf(i.valid_from)} – ${timeOf(i.valid_until)}`;
}

const STATUS_TONE = { active: "ok", revoked: "bad", expired: "neutral" } as const;

// ---------- New invite ----------

function InviteForm({ open, onClose, sites, hosts, purposes, defaultSite }: {
  open: boolean;
  onClose: () => void;
  sites: Opt[];
  hosts?: Opt[]; // admins choose the host
  purposes: { id: string; label: string }[];
  defaultSite?: string | null;
}) {
  const { t } = useS();
  const qc = useQueryClient();
  const blank = { name: "", phone: "", company: "" };
  const [kind, setKind] = useState<Invite["kind"]>("single");
  const [v, setV] = useState({ site_id: defaultSite ?? sites[0]?.id ?? "", host_id: "", purpose_id: "", title: "", notes: "", date: todayIST(), end_date: "", start_time: "10:00", end_time: "18:00" });
  const [guests, setGuests] = useState([blank]);
  const [send, setSend] = useState(true);
  const whatsapp = useAuth().me?.whatsapp_enabled !== false;
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  const m = useMutation({
    mutationFn: () =>
      api<Invite>("/invites", {
        method: "POST",
        body: {
          ...v,
          host_id: v.host_id || undefined,
          purpose_id: v.purpose_id || undefined,
          title: v.title || undefined,
          notes: v.notes || undefined,
          end_date: kind === "multi_day" ? v.end_date : undefined,
          kind,
          send,
          guests: guests.filter((g) => g.name || g.phone).map((g) => ({ ...g, company: g.company || undefined })),
        },
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["invites"] });
      setGuests([blank]);
      setV((x) => ({ ...x, title: "", notes: "" }));
      onClose();
    },
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate();
  };
  const multi = kind !== "single";
  return (
    <Dialog open={open} onClose={onClose} title={t("invites.new")} wide
      footer={<><Button variant="secondary" onClick={onClose}>{t("common.cancel")}</Button><Button form="invite-form" type="submit" busy={m.isPending}>{t("invites.create")}</Button></>}>
      <form id="invite-form" onSubmit={submit} className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-3" role="radiogroup">
          {(["single", "group", "multi_day"] as const).map((k) => (
            <label key={k} className={cx("cursor-pointer rounded-lg border p-3", kind === k ? "border-brand bg-brand-50" : "border-line")}>
              <input type="radio" name="kind" className="sr-only" checked={kind === k} onChange={() => { setKind(k); if (k === "single") setGuests((g) => g.slice(0, 1)); }} />
              <span className="block text-sm font-medium">{t(`invites.kinds.${k}`)}</span>
              <span className="block text-xs text-ink-3">{t(`invites.kindHelp.${k}`)}</span>
            </label>
          ))}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {sites.length > 1 && (
            <Field label={t("invites.site")}>{(id) => <Select id={id} value={v.site_id} onChange={set("site_id")}>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</Select>}</Field>
          )}
          {hosts && (
            <Field label={t("invites.host")}>
              {(id) => (
                <Select id={id} required value={v.host_id} onChange={set("host_id")}>
                  <option value="">—</option>
                  {hosts.map((h) => <option key={h.id} value={h.id}>{h.name}</option>)}
                </Select>
              )}
            </Field>
          )}
          <Field label={t("invites.titleField")}>{(id) => <Input id={id} value={v.title} onChange={set("title")} placeholder={t("invites.titlePlaceholder")} maxLength={200} />}</Field>
          {purposes.length > 0 && (
            <Field label={t("invites.purpose")}>
              {(id) => <Select id={id} value={v.purpose_id} onChange={set("purpose_id")}><option value="">—</option>{purposes.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</Select>}
            </Field>
          )}
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Field label={kind === "multi_day" ? t("invites.startDate") : t("invites.date")}>{(id) => <Input id={id} type="date" required value={v.date} min={todayIST()} onChange={set("date")} />}</Field>
          {kind === "multi_day" && <Field label={t("invites.endDate")}>{(id) => <Input id={id} type="date" required value={v.end_date} min={v.date} onChange={set("end_date")} />}</Field>}
          <Field label={t("invites.from")}>{(id) => <Input id={id} type="time" required value={v.start_time} onChange={set("start_time")} />}</Field>
          <Field label={t("invites.to")}>{(id) => <Input id={id} type="time" required value={v.end_time} onChange={set("end_time")} />}</Field>
        </div>
        <Field label={t("invites.notes")}>{(id) => <Input id={id} value={v.notes} onChange={set("notes")} placeholder={t("invites.notesPlaceholder")} maxLength={500} />}</Field>
        <div className="space-y-2">
          <p className="text-sm font-medium">{t("invites.guests")}</p>
          {guests.map((g, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr] gap-2 sm:grid-cols-[1.2fr_1fr_1fr_auto]">
              <Input aria-label={t("invites.guestName")} placeholder={t("invites.guestName")} required value={g.name} onChange={(e) => setGuests(guests.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
              <Input aria-label={t("invites.guestPhone")} placeholder={t("invites.guestPhone")} type="tel" required value={g.phone} onChange={(e) => setGuests(guests.map((x, j) => (j === i ? { ...x, phone: e.target.value } : x)))} />
              <Input aria-label={t("invites.guestCompany")} placeholder={t("invites.guestCompany")} value={g.company} onChange={(e) => setGuests(guests.map((x, j) => (j === i ? { ...x, company: e.target.value } : x)))} />
              {guests.length > 1 && <Button type="button" variant="ghost" onClick={() => setGuests(guests.filter((_, j) => j !== i))} aria-label={t("invites.remove")}>✕</Button>}
            </div>
          ))}
          {multi && <Button type="button" variant="secondary" size="sm" onClick={() => setGuests([...guests, blank])}>+ {t("invites.addGuest")}</Button>}
        </div>
        {whatsapp ? (
          <Checkbox label={t("invites.send")} checked={send} onChange={(e) => setSend(e.target.checked)} />
        ) : (
          <p className="text-sm text-ink-2">{t("invites.shareYourself")}</p>
        )}
        {m.error && <Alert>{errText(m.error)}</Alert>}
      </form>
    </Dialog>
  );
}

// ---------- Detail ----------

function GuestRow({ invite, g }: { invite: Invite; g: Guest }) {
  const { t } = useS();
  const whatsapp = useAuth().me?.whatsapp_enabled !== false;
  const qc = useQueryClient();
  const [note, setNote] = useState<string | null>(null);
  const act = useMutation({
    mutationFn: (what: "resend" | "revoke") => api<Guest>(`/invites/${invite.id}/guests/${g.id}/${what}`, { method: "POST" }),
    onSuccess: (_, what) => {
      setNote(what === "resend" ? t("invites.resent") : null);
      void qc.invalidateQueries({ queryKey: ik.one(invite.id) });
      void qc.invalidateQueries({ queryKey: ["invites"] });
    },
  });
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="font-medium">{g.name} {g.company && <span className="text-sm font-normal text-ink-3">· {g.company}</span>}</p>
        <p className="text-xs text-ink-3">
          {g.phone} · {g.sent_at ? t("invites.sent") : whatsapp ? t("invites.notSent") : t("invites.notSentShare")}
          {g.consented_at && ` · ${t("invites.consented")}`}
          {g.use_count > 0 && ` · ${t("invites.uses", { n: g.use_count })}`}
        </p>
        {(note || act.error) && <p className={cx("text-xs", act.error ? "text-bad" : "text-ok")}>{act.error ? errText(act.error) : note}</p>}
      </div>
      <Badge tone={g.status === "active" ? "ok" : g.status === "used" ? "neutral" : "bad"}>{t(`invites.guestStatuses.${g.status}`)}</Badge>
      {g.pass_url && (
        <div className="flex gap-1">
          <Button size="sm" variant="ghost" onClick={() => void navigator.clipboard?.writeText(g.pass_url!).then(() => setNote(t("invites.copied")))}>{t("invites.copy")}</Button>
          {g.share_text && (
            <Button size="sm" variant={whatsapp ? "ghost" : "primary"} data-testid="share-pass" onClick={() => openWhatsApp(g.share_text!, g.phone)}>{t("invites.share")}</Button>
          )}
          {whatsapp && (
            <Button size="sm" variant="secondary" busy={act.isPending && act.variables === "resend"} onClick={() => act.mutate("resend")}>{t("invites.resend")}</Button>
          )}
          <Button size="sm" variant="danger" busy={act.isPending && act.variables === "revoke"} onClick={() => act.mutate("revoke")}>{t("invites.revokeGuest")}</Button>
        </div>
      )}
    </li>
  );
}

function InviteDetail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const { t } = useS();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ik.one(id ?? ""), queryFn: () => api<Invite>(`/invites/${id}`), enabled: !!id });
  const [adding, setAdding] = useState({ name: "", phone: "", company: "" });
  const [csvResult, setCsvResult] = useState<string | null>(null);
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ik.one(id ?? "") });
    void qc.invalidateQueries({ queryKey: ["invites"] });
  };
  const revoke = useMutation({ mutationFn: () => api(`/invites/${id}/revoke`, { method: "POST" }), onSuccess: refresh });
  const add = useMutation({
    mutationFn: () => api(`/invites/${id}/guests`, { method: "POST", body: { guests: [{ ...adding, company: adding.company || undefined }] } }),
    onSuccess: () => {
      setAdding({ name: "", phone: "", company: "" });
      refresh();
    },
  });
  const csv = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api<{ added: number; errors: { row: number; errors: string[] }[] }>(`/invites/${id}/guests/import`, { method: "POST", body: fd });
    },
    onSuccess: (r) => {
      setCsvResult(t("invites.imported", { added: r.added, errors: r.errors.length }) + (r.errors.length ? `\n${r.errors.map((e) => `#${e.row}: ${e.errors.join(", ")}`).join("\n")}` : ""));
      refresh();
    },
  });
  const i = q.data;
  return (
    <Dialog open={!!id} onClose={onClose} title={i?.title || (i ? t(`invites.kinds.${i.kind}`) : t("invites.title"))} wide>
      {!i ? (
        <Spinner />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm text-ink-2">
            <Badge tone={STATUS_TONE[i.status]}>{t(`invites.statuses.${i.status}`)}</Badge>
            <span>{inviteWhen(i)}</span>
            <span>· {i.site_name}</span>
            <span>· {i.host_name}</span>
            <span>· {t("invites.arrived", { n: i.arrived_count, total: i.guest_count })}</span>
          </div>
          {i.notes && <p className="rounded-lg bg-paper p-3 text-sm">📝 {i.notes}</p>}
          <ul className="divide-y divide-line rounded-lg border border-line">{i.guests?.map((g) => <GuestRow key={g.id} invite={i} g={g} />)}</ul>
          {i.status === "active" && i.kind !== "single" && (
            <div className="space-y-2 rounded-lg border border-line p-3">
              <p className="text-sm font-medium">{t("invites.addMore")}</p>
              <div className="grid gap-2 sm:grid-cols-[1.2fr_1fr_1fr_auto]">
                <Input placeholder={t("invites.guestName")} value={adding.name} onChange={(e) => setAdding({ ...adding, name: e.target.value })} />
                <Input placeholder={t("invites.guestPhone")} type="tel" value={adding.phone} onChange={(e) => setAdding({ ...adding, phone: e.target.value })} />
                <Input placeholder={t("invites.guestCompany")} value={adding.company} onChange={(e) => setAdding({ ...adding, company: e.target.value })} />
                <Button busy={add.isPending} disabled={!adding.name || !adding.phone} onClick={() => add.mutate()}>{t("invites.addGuest")}</Button>
              </div>
              {add.error && <Alert>{errText(add.error)}</Alert>}
              <div className="flex flex-wrap items-center gap-3 pt-1 text-sm">
                <label className="cursor-pointer font-medium text-brand">
                  {t("invites.importCsv")}
                  <input type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => e.target.files?.[0] && csv.mutate(e.target.files[0])} />
                </label>
                <span className="text-ink-3">{t("invites.csvHelp")}</span>
                <button className="text-brand underline" onClick={() => void downloadTemplate()}>{t("invites.template")}</button>
              </div>
              {csvResult && <Alert tone="ok">{csvResult}</Alert>}
              {csv.error && <Alert>{errText(csv.error)}</Alert>}
            </div>
          )}
          {i.status === "active" && (
            <div className="flex justify-end">
              <Button variant="danger" busy={revoke.isPending} onClick={() => window.confirm(t("invites.revokeConfirm")) && revoke.mutate()}>{t("invites.revoke")}</Button>
            </div>
          )}
          {revoke.error && <Alert>{errText(revoke.error)}</Alert>}
        </div>
      )}
    </Dialog>
  );
}

async function downloadTemplate() {
  const text = await api<string>("/invites/guests/template.csv");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  a.download = "guests-template.csv";
  a.click();
}

// ---------- List ----------

export function InvitesView({ sites, hosts, purposes, defaultSite }: {
  sites: Opt[];
  hosts?: Opt[];
  purposes: { id: string; label: string }[];
  defaultSite?: string | null;
}) {
  const { t } = useS();
  const [status, setStatus] = useState<"" | Invite["status"]>("active");
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const filters = { status: status || undefined, limit: 100 };
  const q = useQuery({ queryKey: ik.list(filters), queryFn: () => api<Page<Invite>>("/invites", { query: filters }) });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm" role="group">
          {(["active", "expired", "revoked", ""] as const).map((s) => (
            <button key={s || "all"} onClick={() => setStatus(s)} className={cx("rounded-md px-3 py-1", status === s ? "bg-brand text-white" : "text-ink-2")}>
              {s ? t(`invites.statuses.${s}`) : t("invites.filterAll")}
            </button>
          ))}
        </div>
        <Button onClick={() => setCreating(true)}>+ {t("invites.new")}</Button>
      </div>
      {q.isLoading ? (
        <Spinner />
      ) : q.error ? (
        <Alert>{errText(q.error)}</Alert>
      ) : !q.data?.items.length ? (
        <p className="rounded-xl border border-dashed border-line-strong py-12 text-center text-sm text-ink-3">{t("invites.none")}</p>
      ) : (
        <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
          {q.data.items.map((i) => (
            <li key={i.id}>
              <button className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left hover:bg-paper" onClick={() => setOpen(i.id)} data-testid="invite-row">
                <div className="min-w-0 basis-full sm:basis-0 sm:flex-1">
                  <p className="font-medium">{i.title || t(`invites.kinds.${i.kind}`)}</p>
                  <p className="text-xs text-ink-3">{inviteWhen(i)} · {i.site_name}{hosts && ` · ${i.host_name}`}</p>
                </div>
                <span className="text-sm text-ink-2">{t("invites.guestsCount", { count: i.guest_count })} · {t("invites.arrived", { n: i.arrived_count, total: i.guest_count })}</span>
                <Badge tone={STATUS_TONE[i.status]}>{t(`invites.statuses.${i.status}`)}</Badge>
              </button>
            </li>
          ))}
        </ul>
      )}
      <InviteForm open={creating} onClose={() => setCreating(false)} sites={sites} hosts={hosts} purposes={purposes} defaultSite={defaultSite} />
      <InviteDetail id={open} onClose={() => setOpen(null)} />
    </div>
  );
}
