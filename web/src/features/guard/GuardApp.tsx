import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { LanguageSwitch } from "@/components/LanguageSwitch";
import { Alert, Button, Spinner, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { errText, useS } from "../staff/i18n";
import { gk, outbox, startOutbox, useGuardSites, useLiveQueue, useOnline, useOutbox, useQueue, type GuardForm, type GuardSite } from "./guardApi";
import { QueuePanel } from "./QueuePanel";
import { ScanPanel } from "./ScanPanel";
import { useKeepPackFresh } from "./offlinePass";
import { useGuardActions } from "./VisitorCard";
import { WalkInForm } from "./WalkInForm";

const SITE_KEY = "vms.guard.site";
type Tab = "scan" | "queue" | "walkin";

function remembered(): string | null {
  try {
    return localStorage.getItem(SITE_KEY);
  } catch {
    return null;
  }
}

function SyncBar() {
  const { t } = useS();
  const online = useOnline();
  const { pending, failed } = useOutbox();
  if (online && !pending.length && !failed.length) return null;
  return (
    <div className="space-y-2 px-4 pt-3">
      {!online && <Alert tone="warn">{t("guard.offline")}</Alert>}
      {pending.length > 0 && (
        <div className="flex items-center justify-between rounded-lg border border-warn/30 bg-warn-50 px-3 py-2 text-sm text-warn" role="status">
          <span>{t("guard.pending", { count: pending.length })}: {pending.map((p) => p.label).join(", ")}</span>
          {online && <button className="font-medium underline" onClick={() => void outbox.flush()}>{t("common.retry")}</button>}
        </div>
      )}
      {failed.length > 0 && (
        <Alert>
          {t("guard.syncFailed")} {failed.map((f) => `${f.label} (${f.error})`).join("; ")}{" "}
          <button className="font-medium underline" onClick={() => outbox.dismissFailed()}>{t("guard.dismiss")}</button>
        </Alert>
      )}
    </div>
  );
}

function Console({ site, sites, onSite }: { site: GuardSite; sites: GuardSite[]; onSite: (id: string) => void }) {
  const { t } = useS();
  const { me, logout } = useAuth();
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("scan");
  const actions = useGuardActions(site.id);
  const q = useQueue(site.id);
  useLiveQueue(site.id);
  useKeepPackFresh(site.id);
  useEffect(() => startOutbox(() => void qc.invalidateQueries({ queryKey: gk.queue(site.id) })), [qc, site.id]);
  const form = useQuery({ queryKey: gk.form(site.id), queryFn: () => api<GuardForm>("/guard/form", { query: { site_id: site.id } }), staleTime: 5 * 60_000 });
  const waiting = (q.data?.expected.length ?? 0) + (q.data?.invites.length ?? 0) + (q.data?.awaiting.length ?? 0);

  return (
    <div className="mx-auto flex min-h-dvh max-w-2xl flex-col bg-paper">
      <header className="sticky top-0 z-10 border-b border-line bg-surface">
        <div className="flex items-center gap-3 px-4 py-2.5">
          <div className="min-w-0 flex-1">
            {sites.length > 1 ? (
              <select value={site.id} onChange={(e) => onSite(e.target.value)} className="max-w-full truncate bg-transparent font-semibold" aria-label={t("guard.chooseSite")}>
                {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </select>
            ) : (
              <p className="truncate font-semibold">{site.name}</p>
            )}
            <p className="truncate text-xs text-ink-3">
              <span data-testid="on-site-count" className="font-medium text-ink-2">{t("guard.peopleOnSite", { count: q.data?.people_on_site ?? 0 })}</span> · {me?.full_name}
            </p>
          </div>
          <LanguageSwitch />
          <button onClick={() => void logout()} className="text-sm text-ink-3 hover:text-ink">{t("common.signOut")}</button>
        </div>
        <nav className="grid grid-cols-3 border-t border-line" role="tablist">
          {(["scan", "queue", "walkin"] as Tab[]).map((k) => (
            <button key={k} role="tab" aria-selected={tab === k} onClick={() => { setTab(k); actions.clear(); }}
              className={cx("relative py-3 text-sm font-medium", tab === k ? "text-brand" : "text-ink-2")}>
              {t(`guard.tabs.${k}`)}
              {k === "queue" && waiting > 0 && <span className="ml-1.5 rounded-full bg-brand px-1.5 text-xs text-white">{waiting}</span>}
              {tab === k && <span className="absolute inset-x-6 bottom-0 h-0.5 rounded bg-brand" />}
            </button>
          ))}
        </nav>
      </header>
      <SyncBar />
      <main className="flex-1 p-4">
        {tab === "scan" && <ScanPanel siteId={site.id} actions={actions} />}
        {tab === "queue" && <QueuePanel siteId={site.id} actions={actions} form={form.data} />}
        {tab === "walkin" && <WalkInForm site={site} form={form.data} />}
      </main>
    </div>
  );
}

export default function GuardApp() {
  const { t } = useS();
  const { logout } = useAuth();
  const sites = useGuardSites();
  const [siteId, setSiteId] = useState<string | null>(remembered);
  const pick = (id: string) => {
    setSiteId(id);
    try {
      localStorage.setItem(SITE_KEY, id);
    } catch {
      /* private mode */
    }
  };
  if (sites.isLoading) return <Spinner label={t("common.loading")} />;
  if (sites.error) return <div className="p-6"><Alert>{errText(sites.error)}</Alert></div>;
  const list = sites.data ?? [];
  const site = list.find((s) => s.id === siteId) ?? (list.length === 1 ? list[0] : undefined);
  if (!list.length) {
    return (
      <div className="mx-auto max-w-md space-y-4 p-6">
        <Alert tone="warn">{t("guard.noSites")}</Alert>
        <Button variant="secondary" onClick={() => void logout()}>{t("common.signOut")}</Button>
      </div>
    );
  }
  if (!site) {
    return (
      <div className="mx-auto max-w-md space-y-3 p-6">
        <div className="flex items-center justify-between"><h1 className="text-lg font-semibold">{t("guard.chooseSite")}</h1><LanguageSwitch /></div>
        {list.map((s) => (
          <button key={s.id} onClick={() => pick(s.id)} className="block w-full rounded-xl border border-line bg-surface px-4 py-4 text-left hover:border-brand">
            <span className="font-semibold">{s.name}</span>
            {s.city && <span className="block text-sm text-ink-3">{s.city}</span>}
          </button>
        ))}
      </div>
    );
  }
  return <Console key={site.id} site={site} sites={list} onSite={pick} />;
}
