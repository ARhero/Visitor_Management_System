import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Alert, Badge, Button, Card, Dialog, Empty, Field, Input, PageHeader, Spinner, cx, td, th } from "@/components/ui";
import { api, downloadFile, errorMessage } from "@/lib/api";
import { useMut } from "./queries";

/** DPDP tools: retention, erasure requests, one person's data, and the privacy notice. */

interface Overview {
  retention: {
    retention_days: number;
    cutoff: string;
    due: number;
    anonymized_visits: number;
    oldest_identifiable: string | null;
    last_run: { at: string; visits: number; visitors: number; guests: number; files: number } | null;
  };
  open_requests: number;
  privacy_url: string;
  privacy_contact: string | null;
}
interface PrivacyRequest {
  id: string;
  phone: string | null;
  phone_masked: string;
  name: string | null;
  reason: string | null;
  status: "open" | "completed" | "rejected";
  resolution_note: string | null;
  resolved_at: string | null;
  resolved_by_name: string | null;
  created_at: string;
  visits: number;
  active_visit: boolean;
}
interface PersonData {
  phone: string;
  visitor: { name: string | null; company: string | null; first_seen: string | null; last_visit: string | null; visit_count: number } | null;
  visits: { id: string; name: string | null; requested_at: string; site: string | null; host: string | null; purpose: string | null; status: string; has_photo: boolean; active: boolean }[];
  invitations: { title: string | null; from: string; status: string }[];
  consents: { notice_version: number; language: string; accepted_at: string; withdrawn_at: string | null }[];
  messages: { at: string; kind: string }[];
  blacklist_entries: number;
}
interface Notice { id: string; locale: string; version: number; body: string; preview: string; is_current: boolean; published_at: string; acceptances: number }
interface Counts { visits: number; visitors: number; guests: number; messages: number; files: number }

const dt = (s: string | null) => (s ? new Date(s).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "numeric", minute: "2-digit" }) : "—");
const day = (s: string | null) => (s ? new Date(s).toLocaleDateString("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" }) : "—");
const summary = (c: Counts) => `${c.visits} visit(s), ${c.visitors} visitor record(s), ${c.guests} invitation(s), ${c.files} file(s)`;

export default function PrivacyPage() {
  const { data } = useQuery({ queryKey: ["privacy", "overview"], queryFn: () => api<Overview>("/privacy/overview") });
  return (
    <>
      <PageHeader
        title="Privacy"
        description={<>Visitor data under the DPDP Act, 2023. Visitors can see, download and ask to erase their data at{" "}
          {data ? <a href={data.privacy_url} target="_blank" rel="noreferrer" className="text-brand hover:underline">{data.privacy_url.replace(/^https?:\/\//, "")}</a> : "…"}.</>}
      />
      {!data ? <Spinner /> : (
        <div className="space-y-6">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <RetentionCard o={data} />
            <LookupCard />
          </div>
          <RequestsCard open={data.open_requests} />
          <NoticesCard />
        </div>
      )}
    </>
  );
}

function RetentionCard({ o }: { o: Overview }) {
  const r = o.retention;
  const [msg, setMsg] = useState<string | null>(null);
  const run = useMut(() => api<Counts>("/privacy/retention/run", { method: "POST" }), [["privacy"]]);
  return (
    <Card title="Retention" actions={<Button size="sm" variant="secondary" busy={run.isPending}
      onClick={() => run.mutate(undefined, { onSuccess: (c) => setMsg(`Done: ${summary(c)} anonymized.`), onError: (e) => setMsg(errorMessage(e)) })}>Run now</Button>}>
      <dl className="grid grid-cols-2 gap-4 text-sm">
        <div><dt className="text-ink-3">Kept for</dt><dd className="text-lg font-semibold">{r.retention_days} days</dd></div>
        <div><dt className="text-ink-3">Due for removal now</dt><dd className="text-lg font-semibold">{r.due}</dd></div>
        <div><dt className="text-ink-3">Oldest identifiable visit</dt><dd>{day(r.oldest_identifiable)}</dd></div>
        <div><dt className="text-ink-3">Anonymized so far</dt><dd>{r.anonymized_visits} visit(s)</dd></div>
      </dl>
      <p className="mt-4 text-xs text-ink-3">
        Runs by itself every 6 hours. Visits before {day(r.cutoff)} lose the name, phone, photo, ID details and message text; counts for reports stay.
        {r.last_run ? ` Last run ${dt(r.last_run.at)}: ${r.last_run.visits} visit(s), ${r.last_run.files} file(s).` : ""}
        {" "}Change the period in <a href="/admin/settings" className="text-brand hover:underline">Settings</a>.
      </p>
      {msg && <p className="mt-2 text-sm text-ink-2" role="status">{msg}</p>}
    </Card>
  );
}

function LookupCard() {
  const [phone, setPhone] = useState("");
  const [data, setData] = useState<PersonData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [erasing, setErasing] = useState(false);
  const [done, setDone] = useState<string | null>(null);

  async function lookup(e?: FormEvent) {
    e?.preventDefault();
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      setData(await api<PersonData>("/privacy/lookup", { query: { phone } }));
    } catch (err) {
      setError(errorMessage(err));
      setData(null);
    } finally {
      setBusy(false);
    }
  }
  const empty = data && !data.visitor && !data.visits.length && !data.invitations.length;
  const active = data?.visits.some((v) => v.active);
  return (
    <Card title="Look up a person">
      <form onSubmit={lookup} className="flex gap-2">
        <Input aria-label="Mobile number" type="tel" required placeholder="Mobile number" value={phone} onChange={(e) => setPhone(e.target.value)} />
        <Button type="submit" variant="secondary" busy={busy} className="shrink-0 whitespace-nowrap">Look up</Button>
      </form>
      {error && <div className="mt-3"><Alert>{error}</Alert></div>}
      {done && <div className="mt-3"><Alert tone="ok">{done}</Alert></div>}
      {data && (empty ? <p className="mt-4 text-sm text-ink-2">No visitor data held for {data.phone}.</p> : (
        <div className="mt-4 space-y-3 text-sm">
          <p><span className="font-medium">{data.visitor?.name ?? data.visits.find((v) => v.name)?.name ?? "Unknown"}</span>
            {data.visitor?.company ? <span className="text-ink-2"> · {data.visitor.company}</span> : null}
            <span className="text-ink-3"> · {data.phone}</span></p>
          <ul className="flex flex-wrap gap-2">
            <li><Badge>{data.visits.length} visit(s)</Badge></li>
            <li><Badge>{data.visits.filter((v) => v.has_photo).length} photo(s)</Badge></li>
            <li><Badge>{data.invitations.length} invitation(s)</Badge></li>
            <li><Badge>{data.consents.length} consent(s)</Badge></li>
            <li><Badge>{data.messages.length} message(s)</Badge></li>
            {data.blacklist_entries > 0 && <li><Badge tone="warn">On the blacklist (kept)</Badge></li>}
          </ul>
          {data.visits.length > 0 && (
            <p className="text-ink-2">Last visit {data.visits[0].requested_at} to {data.visits[0].host ?? "?"} at {data.visits[0].site ?? "?"}{active ? " · visit in progress" : ""}.</p>
          )}
          <div className="flex flex-wrap gap-2 pt-1">
            <Button size="sm" variant="secondary" onClick={() => void downloadFile("/privacy/export", { query: { phone: data.phone }, fallbackName: "visitor-data.zip" })}>Download data (ZIP)</Button>
            <Button size="sm" variant="danger" disabled={active} title={active ? "They have a visit in progress" : undefined} onClick={() => setErasing(true)}>Erase…</Button>
          </div>
        </div>
      ))}
      <EraseDialog open={erasing} phone={data?.phone ?? ""} onClose={() => setErasing(false)}
        onDone={(c) => { setErasing(false); setDone(`Erased: ${summary(c)}.`); void lookup(); }} />
    </Card>
  );
}

function EraseDialog({ open, phone, onClose, onDone }: { open: boolean; phone: string; onClose: () => void; onDone: (c: Counts) => void }) {
  const [confirm, setConfirm] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const erase = useMut(() => api<Counts>("/privacy/erase", { method: "POST", body: { phone, confirm_phone: confirm, note: note || null } }), [["privacy"]]);
  return (
    <Dialog open={open} onClose={onClose} title="Erase this person's data"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="danger" busy={erase.isPending} disabled={!confirm}
          onClick={() => { setError(null); erase.mutate(undefined, { onSuccess: (c) => { setConfirm(""); setNote(""); onDone(c); }, onError: (e) => setError(errorMessage(e)) }); }}>Erase permanently</Button></>}>
      <div className="space-y-4 text-sm">
        <p className="text-ink-2">Names, phone, photos, ID details, answers and message text are removed from every visit and invitation for <span className="font-medium text-ink">{phone}</span>. Visit counts stay for reports. This can't be undone.</p>
        {error && <Alert>{error}</Alert>}
        <Field label="Type the mobile number again">{(i) => <Input id={i} type="tel" value={confirm} onChange={(e) => setConfirm(e.target.value)} />}</Field>
        <Field label="Note for the audit log" hint="Optional, e.g. how the request was made.">{(i) => <Input id={i} maxLength={500} value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
      </div>
    </Dialog>
  );
}

function RequestsCard({ open }: { open: number }) {
  const [showAll, setShowAll] = useState(false);
  const { data, isLoading } = useQuery({
    queryKey: ["privacy", "requests", showAll],
    queryFn: () => api<PrivacyRequest[]>("/privacy/requests", { query: { status: showAll ? undefined : "open" } }),
  });
  const [rejecting, setRejecting] = useState<PrivacyRequest | null>(null);
  const [error, setError] = useState<string | null>(null);
  const erase = useMut((r: PrivacyRequest) => api(`/privacy/requests/${r.id}/erase`, { method: "POST", body: {} }), [["privacy"]]);
  return (
    <Card padded={false} title={<span className="flex items-center gap-2">Erasure requests {open > 0 && <Badge tone="warn">{open} open</Badge>}</span>}
      actions={<label className="flex items-center gap-2 text-sm text-ink-2"><input type="checkbox" className="accent-brand" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />Show handled</label>}>
      {error && <div className="p-4"><Alert>{error}</Alert></div>}
      {isLoading ? <Spinner /> : !data?.length ? (
        <Empty title={showAll ? "No requests yet" : "No open requests"}>Visitors ask from the privacy page after verifying their number. You'll see them here; they're told on WhatsApp when you act.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px]">
            <thead className="border-b border-line"><tr><th className={th}>Person</th><th className={th}>Asked</th><th className={th}>Reason</th><th className={th}>Held</th><th className={th} /></tr></thead>
            <tbody className="divide-y divide-line">
              {data.map((r) => (
                <tr key={r.id}>
                  <td className={td}><span className="font-medium">{r.name ?? "—"}</span><span className="block text-xs text-ink-3">{r.phone ?? r.phone_masked}</span></td>
                  <td className={td}>{dt(r.created_at)}</td>
                  <td className={cx(td, "max-w-xs text-ink-2")}>{r.reason ?? "—"}</td>
                  <td className={td}>{r.status === "open" ? `${r.visits} visit(s)${r.active_visit ? " · on site" : ""}` : "—"}</td>
                  <td className={cx(td, "whitespace-nowrap text-right")}>
                    {r.status === "open" ? (
                      <>
                        <Button size="sm" variant="ghost" onClick={() => setRejecting(r)}>Decline…</Button>
                        <Button size="sm" variant="danger" busy={erase.isPending && erase.variables?.id === r.id} disabled={r.active_visit}
                          title={r.active_visit ? "They have a visit in progress" : undefined}
                          onClick={() => confirm(`Erase all visitor data for ${r.name ?? r.phone}? This can't be undone.`) &&
                            erase.mutate(r, { onError: (e) => setError(errorMessage(e)) })}>Erase</Button>
                      </>
                    ) : (
                      <span className="text-sm text-ink-2">
                        <Badge tone={r.status === "completed" ? "ok" : "neutral"}>{r.status === "completed" ? "Erased" : "Declined"}</Badge>
                        <span className="ml-2 text-xs text-ink-3">{r.resolved_by_name ?? ""} · {day(r.resolved_at)}</span>
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <RejectDialog request={rejecting} onClose={() => setRejecting(null)} />
    </Card>
  );
}

function RejectDialog({ request, onClose }: { request: PrivacyRequest | null; onClose: () => void }) {
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const reject = useMut(() => api(`/privacy/requests/${request?.id}/reject`, { method: "POST", body: { note } }), [["privacy"]]);
  return (
    <Dialog open={!!request} onClose={onClose} title="Decline the request"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button busy={reject.isPending} disabled={note.trim().length < 3}
          onClick={() => reject.mutate(undefined, { onSuccess: () => { setNote(""); onClose(); }, onError: (e) => setError(errorMessage(e)) })}>Decline and tell them</Button></>}>
      <div className="space-y-3 text-sm">
        <p className="text-ink-2">Only decline if you must keep the data, e.g. a legal hold or an incident under investigation. {request?.name ?? "The visitor"} gets your reason on WhatsApp.</p>
        {error && <Alert>{error}</Alert>}
        <Field label="Reason">{(i) => <textarea id={i} rows={3} maxLength={500} className="w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-base sm:text-sm" value={note} onChange={(e) => setNote(e.target.value)} />}</Field>
      </div>
    </Dialog>
  );
}

function NoticesCard() {
  const { data } = useQuery({ queryKey: ["privacy", "notices"], queryFn: () => api<Notice[]>("/privacy/notices") });
  const [locale, setLocale] = useState<"en" | "hi">("en");
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const publish = useMut(() => api<Notice>("/privacy/notices", { method: "POST", body: { locale, body: editing } }), [["privacy", "notices"]]);
  const list = (data ?? []).filter((n) => n.locale === locale);
  const current = list.find((n) => n.is_current);
  return (
    <Card title="Privacy notice" actions={
      <div className="flex rounded-md border border-line p-0.5 text-sm" role="tablist">
        {(["en", "hi"] as const).map((l) => (
          <button key={l} role="tab" aria-selected={locale === l} onClick={() => { setLocale(l); setEditing(null); }}
            className={cx("rounded px-3 py-1", locale === l ? "bg-brand-50 font-medium text-brand" : "text-ink-2")}>{l === "en" ? "English" : "हिन्दी"}</button>
        ))}
      </div>}>
      {!data ? <Spinner /> : (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_260px]">
          <div>
            {editing === null ? (
              <>
                <p className="text-xs font-medium uppercase tracking-wide text-ink-3">Version {current?.version} · what visitors see</p>
                <p className="mt-2 whitespace-pre-line rounded-lg bg-paper p-4 text-sm leading-relaxed">{current?.preview}</p>
                <Button className="mt-3" size="sm" variant="secondary" onClick={() => setEditing(current?.body ?? "")}>Edit and publish a new version</Button>
              </>
            ) : (
              <form onSubmit={(e) => { e.preventDefault(); setError(null); publish.mutate(undefined, { onSuccess: () => setEditing(null), onError: (err) => setError(errorMessage(err)) }); }}>
                {error && <div className="mb-3"><Alert>{error}</Alert></div>}
                <textarea aria-label="Notice text" rows={9} className="w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-base sm:text-sm leading-relaxed" value={editing} onChange={(e) => setEditing(e.target.value)} />
                <p className="mt-1 text-xs text-ink-3">{"{org}"} = your organization's name, {"{days}"} = the retention period, {"{privacy}"} = the link to the visitor privacy page (and your privacy contact). Say what you collect, why, who sees it, how long it's kept and how to ask for erasure.</p>
                <div className="mt-3 flex gap-2">
                  <Button type="submit" busy={publish.isPending}>Publish version {(list[0]?.version ?? 0) + 1}</Button>
                  <Button type="button" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                </div>
              </form>
            )}
          </div>
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-3">History</p>
            <ul className="divide-y divide-line rounded-lg border border-line text-sm">
              {list.map((n) => (
                <li key={n.id} className="flex items-center justify-between px-3 py-2">
                  <span>v{n.version} {n.is_current && <Badge tone="ok">Current</Badge>}<span className="block text-xs text-ink-3">{day(n.published_at)}</span></span>
                  <span className="text-xs text-ink-2">{n.acceptances} accepted</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-ink-3">Old versions are kept, so every visitor's consent points at the exact text they saw. Publishing asks new visitors (and anyone mid check-in) to accept the new text.</p>
          </div>
        </div>
      )}
    </Card>
  );
}
