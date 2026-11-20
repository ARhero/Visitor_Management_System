import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Alert, Card, Input, PageHeader, Select, Spinner, cx, td, th } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { Columns, HBars, Heatmap, StatTile, duration, fmt } from "./charts";
import { istDay, type ApprovalTimes, type DepartmentRow, type PeakHours, type TopHost, type Traffic } from "./insightsApi";
import { useSites } from "./queries";
import { ExportButtons } from "./VisitsPage";

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const dayFmt = new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", timeZone: "UTC" });
const weekday = new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });

function useReport<T>(path: string, q: Record<string, string>) {
  return useQuery({ queryKey: ["report", path, q], queryFn: () => api<T>(`/reports/${path}`, { query: q }), placeholderData: (p) => p });
}

const RANGES = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

export default function ReportsPage() {
  const sites = useSites();
  const [from, setFrom] = useState(istDay(29));
  const [to, setTo] = useState(istDay(0));
  const [siteId, setSiteId] = useState("");
  const q = { from, to, ...(siteId ? { site_id: siteId } : {}) };
  const traffic = useReport<Traffic>("traffic", q);
  const peak = useReport<PeakHours>("peak-hours", q);
  const approval = useReport<ApprovalTimes>("approval-times", q);
  const hosts = useReport<TopHost[]>("top-hosts", q);
  const depts = useReport<DepartmentRow[]>("departments", q);
  const err = traffic.error ?? peak.error ?? approval.error ?? hosts.error ?? depts.error;
  const tr = traffic.data;
  const ap = approval.data;

  return (
    <>
      <PageHeader title="Reports" description="Visits and host response times for a period. Days and hours are IST."
        actions={<ExportButtons kinds={["report_pdf"]} filters={{ from_date: from, to_date: to, site_id: siteId || null }} />} />
      <div className="mb-6 flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm">
          {RANGES.map((r) => (
            <button key={r.label} onClick={() => { setFrom(istDay(r.days - 1)); setTo(istDay(0)); }}
              className={cx("rounded-md px-3 py-1.5", from === istDay(r.days - 1) && to === istDay(0) ? "bg-brand text-white" : "text-ink-2")}>{r.label}</button>
          ))}
        </div>
        <Input type="date" aria-label="From" className="w-40!" value={from} max={to} onChange={(e) => e.target.value && setFrom(e.target.value)} />
        <Input type="date" aria-label="To" className="w-40!" value={to} min={from} onChange={(e) => e.target.value && setTo(e.target.value)} />
        <Select aria-label="Site" className="w-48!" value={siteId} onChange={(e) => setSiteId(e.target.value)}>
          <option value="">All sites</option>
          {sites.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </Select>
      </div>
      {err && <Alert>{errorMessage(err)}</Alert>}
      {!tr || !ap ? <Spinner /> : (
        <div className="space-y-6" data-testid="reports">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <StatTile label="Visits" value={fmt(tr.totals.visits)} hint={`${fmt(tr.totals.requests)} requests`} />
            <StatTile label="People through the gate" value={fmt(tr.totals.people)} hint={`${fmt(tr.totals.unique_visitors)} different visitors`} />
            <StatTile label="Median host answer" value={duration(ap.median_seconds)} hint={`90% within ${duration(ap.p90_seconds)}`} />
            <StatTile label="Never answered" value={fmt(ap.unanswered)} tone={ap.unanswered ? "warn" : undefined} hint={`${ap.escalated} went to a backup host`} />
          </div>
          <Card title="Visits per day">
            <Columns label="Visits" data={tr.days.map((d) => ({
              label: tr.days.length > 14 ? dayFmt.format(new Date(d.day)) : weekday.format(new Date(d.day)),
              title: weekday.format(new Date(d.day)),
              value: d.checked_in,
              detail: [`${d.requests} requests`, d.rejected ? `${d.rejected} declined` : "", d.expired ? `${d.expired} unanswered` : ""].filter(Boolean),
            }))} />
            <p className="mt-1 text-xs text-ink-3">
              Visitors who came in. Of {fmt(tr.totals.requests)} requests: {tr.totals.rejected} declined, {tr.totals.expired} expired, {tr.totals.cancelled} cancelled
              {tr.totals.flagged ? `, ${tr.totals.flagged} matched the blacklist` : ""}.
            </p>
          </Card>
          <div className="grid gap-6 xl:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
            <Card title="When people arrive">
              {peak.data ? <Heatmap grid={peak.data.grid} /> : <Spinner />}
              {peak.data?.busiest && (
                <p className="mt-2 text-sm text-ink-2">
                  Busiest: <strong className="text-ink">{DAYS[peak.data.busiest.weekday]}s, {String(peak.data.busiest.hour).padStart(2, "0")}:00–{String(peak.data.busiest.hour + 1).padStart(2, "0")}:00</strong> ({peak.data.busiest.check_ins} check-ins). Plan guard shifts around it.
                </p>
              )}
            </Card>
            <Card title="How fast hosts answer">
              <Columns label="Answers" height={150} data={ap.buckets.map((b) => ({ label: b.label, value: b.count }))} />
              <p className="mt-1 text-xs text-ink-3">
                {ap.answered} answered ({ap.by_channel.whatsapp} on WhatsApp, {ap.by_channel.web} on the web) · {ap.overrides} let in by security without the host.
              </p>
            </Card>
          </div>
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <Card title="Top hosts" padded={false}>
              {!hosts.data?.length ? <p className="p-5 text-sm text-ink-3">No visits in this period.</p> : (
                <table className="w-full">
                  <thead className="border-b border-line"><tr><th className={th}>Host</th><th className={cx(th, "text-right")}>Visits</th><th className={cx(th, "text-right")}>Median answer</th></tr></thead>
                  <tbody className="divide-y divide-line">
                    {hosts.data.map((h) => (
                      <tr key={h.host_id}>
                        <td className={td}>{h.host_name}<p className="text-xs text-ink-3">{h.department}</p></td>
                        <td className={cx(td, "text-right tabular-nums")}>{h.visits}</td>
                        <td className={cx(td, "text-right tabular-nums")}>{duration(h.median_wait_seconds)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            <div className="space-y-6">
              <Card title="Visits by department">
                <HBars data={(depts.data ?? []).slice(0, 10).map((d) => ({ label: d.department, value: d.visits }))} />
              </Card>
              <Card title="Purpose of visit">
                <HBars data={tr.by_purpose.map((p) => ({ label: p.label, value: p.visits }))} />
                <p className="mt-3 text-xs text-ink-3">
                  Self check-in {tr.by_source.qr_self} · at the desk {tr.by_source.guard_manual} · pre-approved invites {tr.by_source.invite}
                </p>
              </Card>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
