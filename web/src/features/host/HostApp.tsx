import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { LanguageSwitch } from "@/components/LanguageSwitch";
import { Alert, Button, Input, Spinner, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Site } from "@/lib/types";
import { Photo, StatusBadge } from "../guard/VisitorCard";
import { InvitesView } from "../invites/Invites";
import { disablePush } from "@/lib/push";
import { AlertsCard } from "./AlertsCard";
import { HistoryTab } from "./HistoryTab";
import { clock, errText, useS } from "../staff/i18n";

interface HostVisit {
  id: string;
  status: string;
  source: string;
  visitor_name: string | null;
  visitor_company: string | null;
  visitor_phone: string | null;
  photo_url: string | null;
  purpose: string | null;
  purpose_i18n: Record<string, string>;
  purpose_note: string | null;
  accompanying_count: number;
  vehicle_number: string | null;
  site_name: string;
  gate_name: string | null;
  requested_at: string;
  checked_in_at: string | null;
  checked_out_at: string | null;
  host_message: string | null;
  can_respond: boolean;
}

function Waiting({ v }: { v: HostVisit }) {
  const { t, i18n } = useS();
  const qc = useQueryClient();
  const [msg, setMsg] = useState("");
  const [ask, setAsk] = useState<"wait" | "reject" | null>(null);
  const m = useMutation({
    mutationFn: (action: "approve" | "wait" | "reject") =>
      api(`/host/visits/${v.id}/respond`, { method: "POST", body: { action, message: msg.trim() || undefined } }),
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["host"] });
      setAsk(null);
    },
  });
  const purpose = v.purpose_i18n?.[i18n.language] || v.purpose;
  return (
    <li className="space-y-3 p-4" data-testid="host-waiting">
      <div className="flex gap-4">
        <Photo url={v.photo_url} size="lg" />
        <div className="min-w-0 space-y-0.5">
          <p className="text-lg font-semibold">{v.visitor_name}</p>
          {v.visitor_company && <p className="text-ink-2">{v.visitor_company}</p>}
          <p className="text-sm text-ink-2">{[purpose, v.purpose_note].filter(Boolean).join(" · ")}</p>
          <p className="text-xs text-ink-3">
            {v.site_name}{v.gate_name && ` · ${v.gate_name}`} · {clock(v.requested_at)}
            {v.accompanying_count > 0 && ` · ${t("common.people", { n: v.accompanying_count })}`}
          </p>
        </div>
      </div>
      {ask && (
        <Input value={msg} onChange={(e) => setMsg(e.target.value)} placeholder={t("host.message")} maxLength={300} autoFocus aria-label={t("host.message")} />
      )}
      <div className="flex flex-wrap gap-2">
        {ask ? (
          <>
            <Button busy={m.isPending} variant={ask === "reject" ? "danger" : "primary"} onClick={() => m.mutate(ask)}>{t("host.send")}</Button>
            <Button variant="ghost" onClick={() => setAsk(null)}>{t("common.cancel")}</Button>
          </>
        ) : (
          <>
            <Button busy={m.isPending && m.variables === "approve"} onClick={() => m.mutate("approve")}>{t("host.approve")}</Button>
            <Button variant="secondary" onClick={() => setAsk("wait")}>{t("host.wait")}</Button>
            <Button variant="danger" onClick={() => setAsk("reject")}>{t("host.reject")}</Button>
          </>
        )}
      </div>
      {m.error && <Alert>{errText(m.error)}</Alert>}
    </li>
  );
}

function VisitorsTab() {
  const { t } = useS();
  const open = useQuery({ queryKey: ["host", "open"], queryFn: () => api<HostVisit[]>("/host/visits"), refetchInterval: 10_000 });
  const today = useQuery({ queryKey: ["host", "today"], queryFn: () => api<HostVisit[]>("/host/visits/today"), refetchInterval: 20_000 });
  return (
    <div className="space-y-6">
      <AlertsCard />
      <section>
        <h2 className="mb-2 text-sm font-semibold text-ink-2">{t("host.waiting")}</h2>
        {open.isLoading ? <Spinner /> : open.error ? <Alert>{errText(open.error)}</Alert> : !open.data?.length ? (
          <p className="rounded-xl border border-dashed border-line-strong py-8 text-center text-sm text-ink-3">{t("host.noneWaiting")}</p>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">{open.data.map((v) => <Waiting key={v.id} v={v} />)}</ul>
        )}
      </section>
      <section>
        <h2 className="mb-2 text-sm font-semibold text-ink-2">{t("host.today")}</h2>
        {today.isLoading ? <Spinner /> : !today.data?.length ? (
          <p className="text-sm text-ink-3">{t("host.noneToday")}</p>
        ) : (
          <ul className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-surface">
            {today.data.map((v) => (
              <li key={v.id} className="flex items-center gap-3 px-4 py-3">
                <Photo url={v.photo_url} />
                <div className="min-w-0 flex-1">
                  <p className="truncate font-medium">{v.visitor_name}{v.visitor_company && <span className="font-normal text-ink-3"> · {v.visitor_company}</span>}</p>
                  <p className="text-xs text-ink-3">
                    {clock(v.requested_at)}
                    {v.checked_in_at && ` · ${t("guard.card.inSince", { time: clock(v.checked_in_at) })}`}
                    {v.checked_out_at && ` · ${t("guard.card.leftAt", { time: clock(v.checked_out_at) })}`}
                  </p>
                </div>
                <StatusBadge status={v.status} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

/** Visitors / History / Invites. Used full-screen in the host app and inside the admin
 *  panel ("My visitors") for admins who are also hosts. */
export function HostTabs({ wide = false }: { wide?: boolean }) {
  const { t } = useS();
  const [tab, setTab] = useState<"visitors" | "history" | "invites">("visitors");
  const sites = useQuery({ queryKey: ["sites"], queryFn: () => api<Site[]>("/sites") });
  const purposes = useQuery({ queryKey: ["purposes"], queryFn: () => api<{ id: string; label: string }[]>("/purposes") });
  return (
    <>
      <nav className={cx("grid grid-cols-3", wide ? "mb-4 max-w-md rounded-lg border border-line bg-surface" : "border-t border-line")} role="tablist">
        {(["visitors", "history", "invites"] as const).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={cx("relative py-3 text-sm font-medium", tab === k ? "text-brand" : "text-ink-2")}>
            {t(`host.tabs.${k}`)}
            {tab === k && <span className="absolute inset-x-6 bottom-0 h-0.5 rounded bg-brand" />}
          </button>
        ))}
      </nav>
      <div className={wide ? "max-w-3xl" : "p-4"}>
        {tab === "visitors" ? (
          <VisitorsTab />
        ) : tab === "history" ? (
          <HistoryTab />
        ) : (
          <div className="space-y-3">
            <p className="text-sm text-ink-2">{t("invites.intro")}</p>
            {sites.data && (
              <InvitesView
                sites={sites.data.filter((s) => s.is_active).map((s) => ({ id: s.id, name: s.name }))}
                purposes={purposes.data ?? []}
              />
            )}
          </div>
        )}
      </div>
    </>
  );
}

export default function HostApp() {
  const { t } = useS();
  const { me, logout } = useAuth();
  return (
    <div className="mx-auto min-h-dvh max-w-3xl">
      <header className="sticky top-0 z-10 border-b border-line bg-surface">
        <div className="flex items-center gap-3 px-4 py-3">
          <div className="min-w-0 flex-1">
            <p className="truncate font-semibold">{t("host.title")}</p>
            <p className="truncate text-xs text-ink-3">{me?.full_name} · {me?.org?.name}</p>
          </div>
          <LanguageSwitch />
          <button onClick={() => void disablePush().catch(() => undefined).finally(() => void logout())} className="text-sm text-ink-3 hover:text-ink">{t("common.signOut")}</button>
        </div>
      </header>
      <HostTabs />
    </div>
  );
}
