import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { Alert, Badge, Button, Card, Dialog, Empty, Input, PageHeader, Select, Spinner, cx, td, th } from "@/components/ui";
import { api, downloadFile, errorMessage } from "@/lib/api";
import { formatIST, formatPhone } from "@/lib/time";
import { duration } from "./charts";
import { SOURCE_LABEL, STATUS_LABEL, STATUS_TONE, istDay, type ExportJob, type Filters, type VisitDetail, type VisitPage } from "./insightsApi";
import { useSites, useUsers } from "./queries";

const time = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true });
const t = (iso: string | null) => (iso ? time.format(new Date(iso)) : "");
const when = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", hour: "numeric", minute: "2-digit", hour12: true });

/** Builds a file in the background, waits for it, then downloads it. */
export function ExportButtons({ filters, kinds = ["visits_csv", "visits_xlsx", "visits_pdf"] }: { filters: Record<string, unknown>; kinds?: string[] }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const label: Record<string, string> = { visits_csv: "CSV", visits_xlsx: "Excel", visits_pdf: "PDF", report_pdf: "Download PDF report" };
  async function run(kind: string) {
    setBusy(kind);
    setError(null);
    try {
      let job = await api<ExportJob>("/exports", { method: "POST", body: { kind, filters } });
      for (let i = 0; i < 120 && (job.status === "queued" || job.status === "running"); i++) {
        await new Promise((r) => setTimeout(r, 1000));
        job = await api<ExportJob>(`/exports/${job.id}`);
      }
      if (job.status !== "done") throw new Error(job.error ?? "The file could not be built");
      await downloadFile(`/exports/${job.id}/download`, { fallbackName: job.file_name ?? undefined });
    } catch (e) {
      setError(e instanceof Error && !("status" in e) ? e.message : errorMessage(e));
    } finally {
      setBusy(null);
    }
  }
  return (
    <div className="flex flex-col items-end gap-1">
      <div className="flex items-center gap-1">
        {kinds.length > 1 && <span className="mr-1 text-sm text-ink-3">Export</span>}
        {kinds.map((k) => (
          <Button key={k} size="sm" variant="secondary" busy={busy === k} disabled={!!busy} onClick={() => void run(k)}>{label[k]}</Button>
        ))}
      </div>
      {error && <p className="max-w-xs text-right text-xs text-bad">{error}</p>}
    </div>
  );
}

function Detail({ id, onClose }: { id: string | null; onClose: () => void }) {
  const q = useQuery({ queryKey: ["visit", id], queryFn: () => api<VisitDetail>(`/visits/${id}`), enabled: !!id });
  const v = q.data;
  const actor = (e: VisitDetail["timeline"][number]) =>
    e.actor_name ?? ({ visitor: "Visitor", system: "System", host: "Host", guard: "Security" } as Record<string, string>)[e.actor_type] ?? e.actor_type;
  return (
    <Dialog open={!!id} onClose={onClose} title={v?.visitor_name ?? "Visit"} wide>
      {q.error ? <Alert>{errorMessage(q.error)}</Alert> : !v ? <Spinner /> : (
        <div className="grid gap-6 md:grid-cols-[1fr_1.1fr]" data-testid="visit-detail">
          <div className="space-y-4">
            <div className="flex gap-4">
              {v.photo_url ? <img src={v.photo_url} alt="" className="size-24 rounded-xl object-cover ring-1 ring-line" /> : <div className="size-24 rounded-xl bg-paper ring-1 ring-line" />}
              <div className="min-w-0 space-y-1 text-sm">
                <p className="text-lg font-semibold">{v.visitor_name ?? "—"}</p>
                {v.visitor_company && <p className="text-ink-2">{v.visitor_company}</p>}
                <p className="text-ink-2">{formatPhone(v.visitor_phone)}</p>
                <div className="flex flex-wrap gap-1"><Badge tone={STATUS_TONE[v.status]}>{STATUS_LABEL[v.status]}</Badge><Badge>{SOURCE_LABEL[v.source]}</Badge>{v.flagged && <Badge tone="bad">Blacklist</Badge>}</div>
              </div>
            </div>
            {v.alert_reason && <Alert tone="warn">Blacklist: {v.alert_reason}</Alert>}
            <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1.5 text-sm">
              <dt className="text-ink-3">Host</dt><dd>{v.host_name}{v.department && <span className="text-ink-3"> · {v.department}</span>}</dd>
              <dt className="text-ink-3">Where</dt><dd>{v.site_name}{v.gate_name && ` · ${v.gate_name}`}</dd>
              <dt className="text-ink-3">Purpose</dt><dd>{[v.purpose, v.purpose_note, v.invite_title].filter(Boolean).join(" · ") || "—"}</dd>
              {v.accompanying_count > 0 && <><dt className="text-ink-3">With them</dt><dd>{v.accompanying_count} more</dd></>}
              {v.vehicle_number && <><dt className="text-ink-3">Vehicle</dt><dd>{v.vehicle_number}</dd></>}
              {v.id_type && <><dt className="text-ink-3">ID</dt><dd>{v.id_type.replace("_", " ")} ••{v.id_last4}</dd></>}
              {Object.entries(v.custom_values).map(([k, val]) => (
                <Fragment key={k}><dt className="text-ink-3">{k.replace(/_/g, " ")}</dt><dd>{typeof val === "object" && val ? "Accepted" : String(val)}</dd></Fragment>
              ))}
              <dt className="text-ink-3">Host answered</dt><dd>{v.wait_seconds !== null ? `in ${duration(v.wait_seconds)} (${v.response_channel})` : "—"}</dd>
              {v.host_message && <><dt className="text-ink-3">Host's note</dt><dd>“{v.host_message}”</dd></>}
              {v.guard_note && <><dt className="text-ink-3">Let in by security</dt><dd>{v.guard_note}</dd></>}
              <dt className="text-ink-3">Privacy notice</dt><dd>{v.consent ? `Version ${v.consent.version} (${v.consent.locale}), ${formatIST(v.consent.at)}` : "—"}</dd>
            </dl>
          </div>
          <div className="space-y-4">
            <div>
              <h3 className="mb-2 text-sm font-semibold">Timeline</h3>
              <ol className="relative space-y-3 border-l border-line pl-4">
                {v.timeline.map((e, i) => (
                  <li key={i} className="text-sm">
                    <span className="absolute -left-[5px] mt-1.5 size-2.5 rounded-full border-2 border-surface bg-brand" />
                    <p><span className="font-medium">{STATUS_LABEL[e.to_status] ?? e.to_status}</span>{e.from_status === e.to_status && " (escalated)"}</p>
                    <p className="text-xs text-ink-3">{formatIST(e.at)} · {actor(e)} via {e.channel}{typeof e.meta.reason === "string" && ` · ${e.meta.reason.replace(/_/g, " ")}`}</p>
                  </li>
                ))}
              </ol>
            </div>
            {v.messages.length > 0 && (
              <div>
                <h3 className="mb-2 text-sm font-semibold">WhatsApp messages</h3>
                <ul className="space-y-1 text-xs text-ink-2">
                  {v.messages.map((m, i) => <li key={i}>{t(m.at)} · {m.direction === "in" ? "from" : "to"} {m.to} · {m.template.replace(/_/g, " ")} · {m.status}</li>)}
                </ul>
              </div>
            )}
          </div>
        </div>
      )}
    </Dialog>
  );
}

const PRESETS = [
  { label: "Today", from: () => istDay(0) },
  { label: "7 days", from: () => istDay(6) },
  { label: "30 days", from: () => istDay(29) },
];

export default function VisitsPage() {
  const [params, setParams] = useSearchParams();
  const sites = useSites();
  const hosts = useUsers({ role: "host", limit: 500 });
  const f: Filters = {
    from: params.get("from") ?? istDay(6),
    to: params.get("to") ?? istDay(0),
    site_id: params.get("site_id") ?? "",
    host_id: params.get("host_id") ?? "",
    status: params.get("status") ?? "",
    q: params.get("q") ?? "",
  };
  const [q, setQ] = useState(f.q ?? "");
  // Start from the live URL, not this render's copy: a debounced search and a click
  // landing together must not overwrite each other (that once dropped the search from
  // an export).
  const set = (patch: Partial<Filters & { open: string }>) => {
    const next = new URLSearchParams(window.location.search);
    for (const [k, v] of Object.entries(patch)) (v ? next.set(k, v) : next.delete(k));
    setParams(next, { replace: true });
  };
  useEffect(() => {
    const id = setTimeout(() => q !== f.q && set({ q }), 300);
    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const query = Object.fromEntries(Object.entries(f).filter(([, v]) => v));
  const list = useInfiniteQuery({
    queryKey: ["visits", query],
    queryFn: ({ pageParam }) => api<VisitPage>("/visits", { query: { ...query, cursor: pageParam, limit: 50 } }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const rows = list.data?.pages.flatMap((p) => p.items) ?? [];
  const total = list.data?.pages[0]?.total;
  const exportFilters = { from_date: f.from, to_date: f.to, site_id: f.site_id || null, host_id: f.host_id || null, status: f.status ? [f.status] : [], q: f.q || null };

  return (
    <>
      <PageHeader title="Visit log" description="Every visit, searchable. Times are IST." actions={<ExportButtons filters={exportFilters} />} />
      <div className="mb-4 flex flex-wrap items-end gap-2">
        <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm">
          {PRESETS.map((p) => (
            <button key={p.label} onClick={() => set({ from: p.from(), to: istDay(0) })}
              className={cx("rounded-md px-3 py-1.5", f.from === p.from() && f.to === istDay(0) ? "bg-brand text-white" : "text-ink-2")}>{p.label}</button>
          ))}
        </div>
        <Input type="date" aria-label="From" className="w-40!" value={f.from} max={f.to} onChange={(e) => set({ from: e.target.value })} />
        <Input type="date" aria-label="To" className="w-40!" value={f.to} min={f.from} onChange={(e) => set({ to: e.target.value })} />
        <Select aria-label="Site" className="w-44!" value={f.site_id} onChange={(e) => set({ site_id: e.target.value })}>
          <option value="">All sites</option>
          {sites.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </Select>
        <Select aria-label="Host" className="w-44!" value={f.host_id} onChange={(e) => set({ host_id: e.target.value })}>
          <option value="">All hosts</option>
          {hosts.data?.items.map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
        </Select>
        <Select aria-label="Status" className="w-40!" value={f.status} onChange={(e) => set({ status: e.target.value })}>
          <option value="">Any status</option>
          {Object.entries(STATUS_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </Select>
        <Input type="search" aria-label="Search" className="w-60!" placeholder="Name, company, phone, vehicle" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Card padded={false}>
        {list.isLoading ? <Spinner /> : list.error ? <div className="p-4"><Alert>{errorMessage(list.error)}</Alert></div> : !rows.length ? (
          <Empty title="No visits match">Try a wider date range or clear the filters.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full" data-testid="visit-log">
              <thead className="border-b border-line"><tr>
                <th className={th}>When</th><th className={th}>Visitor</th><th className={th}>Host</th><th className={th}>Site</th>
                <th className={th}>Status</th><th className={th}>In – out</th><th className={th}>Answer</th>
              </tr></thead>
              <tbody className="divide-y divide-line">
                {rows.map((v) => (
                  <tr key={v.id} className="cursor-pointer hover:bg-paper" onClick={() => set({ open: v.id })}>
                    <td className={cx(td, "whitespace-nowrap text-ink-2")}>{when.format(new Date(v.requested_at))}</td>
                    <td className={cx(td, "min-w-44")}>
                      <p className="font-medium">{v.visitor_name ?? "—"} {v.flagged && <span title="Blacklist match" className="text-bad">⚑</span>}</p>
                      <p className="text-xs text-ink-3">{[v.visitor_company, v.purpose].filter(Boolean).join(" · ")}</p>
                    </td>
                    <td className={td}>{v.host_name}<p className="text-xs text-ink-3">{v.department}</p></td>
                    <td className={td}>{v.site_name}<p className="text-xs text-ink-3">{v.gate_name ?? SOURCE_LABEL[v.source]}</p></td>
                    <td className={td}><Badge tone={STATUS_TONE[v.status]}>{STATUS_LABEL[v.status]}</Badge></td>
                    <td className={cx(td, "whitespace-nowrap tabular-nums text-ink-2")}>{v.checked_in_at ? `${t(v.checked_in_at)} – ${t(v.checked_out_at)}${v.checkout_method === "auto" ? " (auto)" : ""}` : "—"}</td>
                    <td className={cx(td, "tabular-nums text-ink-2")}>{duration(v.wait_seconds)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {rows.length > 0 && (
          <div className="flex items-center justify-between border-t border-line px-4 py-3 text-sm text-ink-3">
            <span>{rows.length} of {total ?? rows.length}</span>
            {list.hasNextPage && <Button size="sm" variant="secondary" busy={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>Load more</Button>}
          </div>
        )}
      </Card>
      <Detail id={params.get("open")} onClose={() => set({ open: "" })} />
    </>
  );
}
