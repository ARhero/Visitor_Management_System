import { useInfiniteQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Alert, Button, Input, Spinner, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { Photo, StatusBadge } from "../guard/VisitorCard";
import { clock, errText, useS } from "../staff/i18n";

interface Row {
  id: string;
  status: string;
  visitor_name: string | null;
  visitor_company: string | null;
  purpose: string | null;
  site_name: string;
  requested_at: string;
  checked_in_at: string | null;
  checked_out_at: string | null;
}

const day = (daysAgo: number) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date(Date.now() - daysAgo * 86_400_000));
const dateFmt = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric" });

/** The host's own past visitors (the API limits a host to their own visits). */
export function HistoryTab() {
  const { t } = useS();
  const [days, setDays] = useState(30);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  useEffect(() => {
    const id = setTimeout(() => setSearch(q.trim()), 300);
    return () => clearTimeout(id);
  }, [q]);
  const query = { from: day(days - 1), to: day(0), q: search || undefined, limit: 30 };
  const list = useInfiniteQuery({
    queryKey: ["host", "history", query],
    queryFn: ({ pageParam }) => api<{ items: Row[]; next_cursor: string | null; total: number | null }>("/visits", { query: { ...query, cursor: pageParam } }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (p) => p.next_cursor ?? undefined,
  });
  const rows = list.data?.pages.flatMap((p) => p.items) ?? [];
  // Group by day.
  const groups: [string, Row[]][] = [];
  for (const r of rows) {
    const d = dateFmt.format(new Date(r.requested_at));
    if (groups.at(-1)?.[0] !== d) groups.push([d, []]);
    groups.at(-1)![1].push(r);
  }
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        <div className="inline-flex rounded-lg border border-line bg-surface p-0.5 text-sm">
          {[7, 30, 90].map((d) => (
            <button key={d} onClick={() => setDays(d)} className={cx("rounded-md px-3 py-1", days === d ? "bg-brand text-white" : "text-ink-2")}>{t(`host.history.range.${d}`)}</button>
          ))}
        </div>
        <Input type="search" className="min-w-0 flex-1" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("host.history.search")} aria-label={t("host.history.search")} />
      </div>
      {list.isLoading ? <Spinner /> : list.error ? <Alert>{errText(list.error)}</Alert> : !rows.length ? (
        <p className="rounded-xl border border-dashed border-line-strong py-8 text-center text-sm text-ink-3">{t("host.history.empty")}</p>
      ) : (
        <>
          <p className="text-xs text-ink-3">{t("host.history.count", { n: list.data?.pages[0]?.total ?? rows.length })}</p>
          {groups.map(([d, rs]) => (
            <section key={d}>
              <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-3">{d}</h3>
              <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface" data-testid="host-history">
                {rs.map((v) => (
                  <li key={v.id} className="flex items-center gap-3 px-4 py-3">
                    <Photo url={null} />
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{v.visitor_name}{v.visitor_company && <span className="font-normal text-ink-3"> · {v.visitor_company}</span>}</p>
                      <p className="truncate text-xs text-ink-3">
                        {[v.purpose, v.site_name, clock(v.requested_at)].filter(Boolean).join(" · ")}
                        {v.checked_in_at && ` · ${t("guard.card.inSince", { time: clock(v.checked_in_at) })}`}
                      </p>
                    </div>
                    <StatusBadge status={v.status} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
          {list.hasNextPage && <Button variant="secondary" className="w-full" busy={list.isFetchingNextPage} onClick={() => void list.fetchNextPage()}>{t("host.history.more")}</Button>}
        </>
      )}
    </div>
  );
}
