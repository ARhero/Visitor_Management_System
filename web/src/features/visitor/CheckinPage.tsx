import { useLoad } from "./useLoad";
import { lazy, Suspense, useEffect, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "react-router";
import { Alert, Field, Input, Spinner, cx } from "@/components/ui";
import { ApiError } from "@/lib/errors";
import { languageChosen } from "@/lib/i18n";

import { BigButton, Panel, PublicShell } from "./PublicShell";
import { errorText, useT } from "./i18n";
import { pub, store, type GateInfo, type Prefill } from "./publicApi";
import { fromPrefill, type Form, type Session } from "./checkinForm";

// Details, photo and confirm come in a second chunk, fetched while the visitor types
// their number (see the effect below), so the first screen needs less.
const loadSteps = () => import("./CheckinSteps");
const DetailsStep = lazy(() => loadSteps().then((m) => ({ default: m.DetailsStep })));
const PhotoStep = lazy(() => loadSteps().then((m) => ({ default: m.PhotoStep })));
const ConfirmStep = lazy(() => loadSteps().then((m) => ({ default: m.ConfirmStep })));

type Step = "phone" | "otp" | "details" | "photo" | "confirm";
const WITH_CODE: Step[] = ["phone", "otp", "details", "photo", "confirm"];
// No WhatsApp code (codes off for this org, or no WhatsApp at all): the number is just
// typed in, and the guard checks ID at the gate instead.
const WITHOUT_CODE: Step[] = ["phone", "details", "photo", "confirm"];

function toE164(raw: string) {
  const d = raw.replace(/\D/g, "");
  if (d.length === 10) return `+91${d}`;
  if (d.length === 12 && d.startsWith("91")) return `+${d}`;
  return raw.trim();
}

export default function CheckinPage() {
  const { gateToken = "" } = useParams();
  const { t, i18n } = useT();
  const nav = useNavigate();
  const lang = i18n.language;
  const gate = useLoad(`gate:${gateToken}`, () => pub<GateInfo>(`/gates/${gateToken}`));

  const key = `vms.v.${gateToken}`;
  const [session, setSession] = useState<Session | null>(() => {
    const s = store.get(key);
    const v = s ? (JSON.parse(s) as Session) : null;
    return v && v.exp > Date.now() ? v : null;
  });
  const [step, setStep] = useState<Step>(session ? "details" : "phone");
  const [phone, setPhone] = useState("");
  const [form, setForm] = useState<Form>(() => fromPrefill(session?.prefill));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const id = setTimeout(() => void loadSteps(), 1500);
    return () => clearTimeout(id);
  }, []);

  // Use the org's default language on first visit, unless the visitor already picked one.
  useEffect(() => {
    if (gate.data && !languageChosen() && gate.data.default_locale !== lang) {
      void i18n.changeLanguage(gate.data.default_locale);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gate.data]);

  function startSession(s: Session) {
    store.set(key, JSON.stringify(s));
    setSession(s);
    setForm(fromPrefill(s.prefill));
    setStep("details");
  }
  function sessionLost(e: unknown) {
    if (e instanceof ApiError && e.status === 401) {
      store.set(key, null);
      setSession(null);
      setStep("phone");
    }
    setError(errorText(e));
  }

  if (gate.isLoading) return <PublicShell><Spinner /></PublicShell>;
  if (gate.error || !gate.data) {
    return (
      <PublicShell>
        <Panel>
          <p className="text-base">{errorText(gate.error)}</p>
        </Panel>
      </PublicShell>
    );
  }
  const g = gate.data;
  const noCode = g.verify_phone === false;
  const STEPS = noCode ? WITHOUT_CODE : WITH_CODE;
  const idx = STEPS.indexOf(step);

  return (
    <PublicShell org={g.org_name} sub={`${g.site_name} · ${g.gate_name}`} color={g.branding.primary_color} logo={g.logo_url}>
      <div className="mb-3 flex items-center justify-between text-sm text-ink-3">
        <span>{t("step", { n: idx + 1, total: STEPS.length })}</span>
        {(step === "photo" || step === "confirm") && (
          <button className="text-brand" onClick={() => { setError(null); setStep(STEPS[idx - 1]); }}>
            ← {t("back")}
          </button>
        )}
      </div>
      <div className="mb-4 flex gap-1" aria-hidden>
        {STEPS.map((s, i) => (
          <span key={s} className={cx("h-1 flex-1 rounded-full", i <= idx ? "bg-brand" : "bg-line")} />
        ))}
      </div>
      {error && <div className="mb-4"><Alert>{error}</Alert></div>}

      {step === "phone" && (
        <PhoneStep gateToken={gateToken} phone={phone} setPhone={setPhone} noCode={noCode}
          onSent={() => { setError(null); setStep("otp"); }}
          onStarted={(s) => { setError(null); startSession(s); }} onError={setError} />
      )}
      {step === "otp" && (
        <OtpStep gateToken={gateToken} phone={toE164(phone)} onBack={() => { setError(null); setStep("phone"); }}
          onVerified={(s) => { setError(null); startSession(s); }} onError={setError} />
      )}
      <Suspense fallback={<Spinner />}>
      {step === "details" && session && (
        <DetailsStep g={g} session={session} form={form} setForm={setForm} lang={lang} onError={sessionLost}
          onNext={() => { setError(null); setStep("photo"); }} />
      )}
      {step === "photo" && session && (
        <PhotoStep g={g} session={session} form={form} setForm={setForm} onError={sessionLost}
          onNext={() => { setError(null); setStep("confirm"); }} />
      )}
      {step === "confirm" && session && (
        <ConfirmStep g={g} session={session} form={form} lang={lang} onError={sessionLost}
          onDone={(visitId, token) => {
            store.set(`vms.visit.${visitId}`, token);
            store.set(key, null);
            nav(`/visit/${visitId}`, { replace: true });
          }} />
      )}
      </Suspense>
    </PublicShell>
  );
}


// ---------- Steps ----------

function PhoneStep({ gateToken, phone, setPhone, noCode, onSent, onStarted, onError }: {
  gateToken: string; phone: string; setPhone: (p: string) => void; noCode: boolean;
  onSent: () => void; onStarted: (s: Session) => void; onError: (m: string) => void;
}) {
  const { t, i18n } = useT();
  const [busy, setBusy] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      if (noCode) {
        const p = toE164(phone);
        const r = await pub<{ token: string; expires_in: number }>("/start", { body: { gate_token: gateToken, phone: p, locale: i18n.language } });
        onStarted({ token: r.token, phone: p, exp: Date.now() + r.expires_in * 1000, prefill: null });
        return;
      }
      await pub("/otp/send", { body: { gate_token: gateToken, phone: toE164(phone), locale: i18n.language } });
      onSent();
    } catch (err) {
      if (err instanceof ApiError && err.code === "otp_cooldown") onSent(); // a code is already on its way
      else onError(errorText(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Panel>
      <h1 className="text-xl font-semibold">{t("phone.title")}</h1>
      <p className="mt-1 text-sm text-ink-2">{t(noCode ? "phone.helpNoCode" : "phone.help")}</p>
      <form onSubmit={submit} className="mt-5 space-y-4">
        <Field label={t("phone.label")}>
          {(id) => (
            <div className="flex">
              <span className="inline-flex h-12 items-center rounded-l-lg border border-r-0 border-line-strong bg-paper px-3 text-base text-ink-2">+91</span>
              <Input id={id} type="tel" inputMode="tel" autoComplete="tel-national" required autoFocus value={phone}
                onChange={(e) => setPhone(e.target.value)} className="h-12 rounded-l-none text-base" placeholder="98765 43210" />
            </div>
          )}
        </Field>
        <BigButton type="submit" busy={busy} disabled={phone.replace(/\D/g, "").length < 10}>{t(noCode ? "phone.continue" : "phone.send")}</BigButton>
      </form>
    </Panel>
  );
}

function OtpStep({ gateToken, phone, onBack, onVerified, onError }: {
  gateToken: string; phone: string; onBack: () => void; onVerified: (s: Session) => void; onError: (m: string) => void;
}) {
  const { t, i18n } = useT();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [wait, setWait] = useState(30);
  useEffect(() => {
    if (wait <= 0) return;
    const id = setTimeout(() => setWait(wait - 1), 1000);
    return () => clearTimeout(id);
  }, [wait]);

  async function verify(c: string) {
    setBusy(true);
    try {
      const r = await pub<{ token: string; expires_in: number; returning: Prefill | null }>("/otp/verify", { body: { gate_token: gateToken, phone, code: c } });
      onVerified({ token: r.token, phone, exp: Date.now() + r.expires_in * 1000, prefill: r.returning });
    } catch (err) {
      onError(errorText(err));
      setCode("");
    } finally {
      setBusy(false);
    }
  }
  async function resend() {
    try {
      await pub("/otp/send", { body: { gate_token: gateToken, phone, locale: i18n.language } });
      setWait(30);
    } catch (err) {
      onError(errorText(err));
    }
  }
  const pretty = phone.replace(/^\+91(\d{5})(\d{5})$/, "+91 $1 $2");
  return (
    <Panel>
      <h1 className="text-xl font-semibold">{t("otp.title")}</h1>
      <p className="mt-1 text-sm text-ink-2">{t("otp.help", { phone: pretty })}</p>
      <form onSubmit={(e) => { e.preventDefault(); void verify(code); }} className="mt-5 space-y-4">
        <Field label={t("otp.label")}>
          {(id) => (
            <Input id={id} inputMode="numeric" autoComplete="one-time-code" pattern="\d{6}" maxLength={6} required autoFocus
              value={code} className="h-14 text-center font-mono text-2xl tracking-[0.5em]"
              onChange={(e) => {
                const c = e.target.value.replace(/\D/g, "").slice(0, 6);
                setCode(c);
                if (c.length === 6) void verify(c);
              }} />
          )}
        </Field>
        <BigButton type="submit" busy={busy} disabled={code.length !== 6}>{t("otp.verify")}</BigButton>
      </form>
      <div className="mt-4 flex justify-between text-sm">
        <button className="text-brand" onClick={onBack}>{t("otp.change")}</button>
        {wait > 0 ? <span className="text-ink-3">{t("otp.resendIn", { s: wait })}</span>
          : <button className="text-brand" onClick={() => void resend()}>{t("otp.resend")}</button>}
      </div>
    </Panel>
  );
}
