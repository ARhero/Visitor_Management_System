import { useState } from "react";
import { Link } from "react-router";
import { Alert, Badge, Card, PageHeader, Select, Spinner } from "@/components/ui";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Columns, HBars, StatTile, duration } from "./charts";
import { STATUS_LABEL, STATUS_TONE, useLive, useOrgLive } from "./insightsApi";
import { SetupChecklist } from "./OverviewPage";
import { useSites } from "./queries";

const time = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true });
const ACTOR: Record<string, string> = { visitor: "visitor", host: "host", guard: "security", system: "system", admin: "admin" };

export default function DashboardPage() {
  const { me } = useAuth();
  const sites = useSites();
  const [siteId, setSiteId] = useState("");
  const live = useLive(siteId);
  useOrgLive([["dashboard", "live"]]);
  const d = live.data;
  const nowHour = Number(new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", hour12: false }).format(new Date()));

  return (
    <>
      <PageHeader
        title={`Today at ${me?.org?.name ?? ""}`}
        description={d ? `Live · updated ${time.format(new Date(d.at))}` : "Live"}
        actions={
          <>
            {(sites.data?.filter((s) => s.is_active).length ?? 0) > 1 && (
              <Select value={siteId} onChange={(e) => setSiteId(e.target.value)} aria-label="Site" className="w-56!">
                <option value="">All sites</option>
                {sites.data?.filter((s) => s.is_active).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
            )}
            <Link to={`/admin/evacuation${siteId ? `?site=${siteId}` : ""}`} className="inline-flex h-10 items-center rounded-lg border border-bad/30 bg-surface px-4 text-sm font-medium text-bad hover:bg-bad-50">
              Evacuation list
            </Link>
          </>
        }
      />
      <SetupChecklist />
      {live.error && <Alert>{errorMessage(live.error)}</Alert>}
      {!d ? (
        <Spinner />
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4" data-testid="live-tiles">
            <StatTile label="People on site" value={d.people_on_site} hint={`${d.on_site} visitor${d.on_site === 1 ? "" : "s"} + people with them`} />
            <StatTile label="Waiting for a host" value={d.waiting_for_host} tone={d.waiting_for_host ? "warn" : undefined} hint={`${d.approved_not_arrived} approved, not arrived yet`} />
            <StatTile label="Checked in today" value={d.today.checked_in} hint={`${d.today.requests} requests · ${d.today.checked_out} left`} />
            <StatTile label="Median host answer today" value={duration(d.median_wait_seconds_today)}
              hint={[d.today.rejected && `${d.today.rejected} declined`, d.today.expired && `${d.today.expired} unanswered`, d.today.blocked && `${d.today.blocked} stopped`].filter(Boolean).join(" · ") || "No declines today"} />
          </div>
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <Card title="Check-ins by hour today (IST)">
              <Columns
                label="Check-ins"
                every={3}
                data={d.by_hour.slice(6, Math.max(nowHour + 1, 21)).map((v, i) => {
                  const h = i + 6;
                  return { label: `${h % 12 || 12}${h < 12 ? "a" : "p"}`, title: `${String(h).padStart(2, "0")}:00–${String(h + 1).padStart(2, "0")}:00`, value: v };
                })}
              />
            </Card>
            <Card title="Check-ins by gate today">
              <HBars empty="No check-ins yet today" data={d.by_gate.map((g) => ({ label: g.gate, sub: siteId ? undefined : g.site, value: g.check_ins }))} />
            </Card>
          </div>
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
            <Card title="On site now" padded={false}>
              <ul className="divide-y divide-line">
                {d.by_site.map((s) => (
                  <li key={s.site_id} className="flex items-center justify-between px-5 py-3 text-sm">
                    <span>{s.site}</span>
                    <span className="tabular-nums text-ink-2"><strong className="text-ink">{s.people}</strong> people · {s.on_site} visitors</span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title="Latest activity" padded={false} actions={<Link to="/admin/visits" className="text-sm text-brand hover:underline">Visit log →</Link>}>
              {d.recent.length === 0 ? (
                <p className="px-5 py-6 text-sm text-ink-3">Nothing yet today.</p>
              ) : (
                <ul className="divide-y divide-line">
                  {d.recent.map((e, i) => (
                    <li key={i} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                      <span className="w-16 shrink-0 tabular-nums text-xs text-ink-3">{time.format(new Date(e.at))}</span>
                      <span className="min-w-0 flex-1 truncate">
                        <Link to={`/admin/visits?open=${e.visit_id}`} className="font-medium hover:underline">{e.visitor ?? "Visitor"}</Link>
                        <span className="text-ink-3"> · {e.site} · by {ACTOR[e.actor] ?? e.actor}</span>
                      </span>
                      <Badge tone={STATUS_TONE[e.to] ?? "neutral"}>{STATUS_LABEL[e.to] ?? e.to}</Badge>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </div>
      )}
    </>
  );
}
