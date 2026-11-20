import { useEffect, useState } from "react";
import { Button } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { disablePush, enablePush, pushState, syncPush, testPush, type PushState } from "@/lib/push";
import { errText, useS } from "../staff/i18n";

/** "Turn on alerts": visitor requests as phone notifications (web push). */
export function AlertsCard() {
  const { t } = useS();
  const { me } = useAuth();
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const noWhatsApp = me?.whatsapp_enabled === false;

  useEffect(() => {
    void pushState().then((s) => {
      setState(s);
      if (s === "on") void syncPush().catch(() => undefined);
    });
  }, []);

  async function run(fn: () => Promise<unknown>, done?: string) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      if (done) setMsg(done);
    } catch (e) {
      setMsg(e instanceof Error && (e.message === "denied" || e.message === "dismissed") ? t(`host.alerts.${e.message}`) : errText(e));
    } finally {
      setState(await pushState());
      setBusy(false);
    }
  }

  if (state === null) return null;
  const on = state === "on";
  return (
    <section className="rounded-xl border border-line bg-surface p-4" data-testid="alerts-card" data-state={state}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="font-medium">{t(on ? "host.alerts.onTitle" : "host.alerts.title")}</p>
          <p className="mt-0.5 text-sm text-ink-2">
            {on ? t("host.alerts.onHelp")
              : state === "needs-install" ? t("host.alerts.install")
              : state === "denied" ? t("host.alerts.blocked")
              : state === "unsupported" ? t("host.alerts.unsupported")
              : t(noWhatsApp ? "host.alerts.helpNoWhatsApp" : "host.alerts.help")}
          </p>
        </div>
        <div className="flex gap-2">
          {state === "off" && (
            <Button busy={busy} onClick={() => void run(enablePush, t("host.alerts.enabled"))}>{t("host.alerts.turnOn")}</Button>
          )}
          {on && (
            <>
              <Button variant="secondary" busy={busy} onClick={() => void run(testPush, t("host.alerts.testSent"))}>{t("host.alerts.test")}</Button>
              <Button variant="ghost" disabled={busy} onClick={() => void run(disablePush)}>{t("host.alerts.turnOff")}</Button>
            </>
          )}
        </div>
      </div>
      {msg && <p className="mt-2 text-sm text-ink-2" role="status">{msg}</p>}
    </section>
  );
}
