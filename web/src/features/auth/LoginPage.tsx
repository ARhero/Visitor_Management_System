import { useEffect, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router";
import { Alert, Button, Field, Input } from "@/components/ui";
import { ApiError, api, errorMessage } from "@/lib/api";
import { homeFor, useAuth } from "@/lib/auth";
import { LanguageSwitch } from "@/components/LanguageSwitch";

export default function LoginPage() {
  const { t } = useTranslation();
  const { me, login } = useAuth();
  const nav = useNavigate();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [orgs, setOrgs] = useState<{ slug: string; name: string }[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [params] = useSearchParams();
  const [mode, setMode] = useState<"password" | "link">(params.get("link") ? "link" : "password");
  const [phone, setPhone] = useState("");
  const [sent, setSent] = useState(false);
  // Without WhatsApp no link can be sent; people get one from their admin instead.
  const [whatsapp, setWhatsapp] = useState(true);
  const [signup, setSignup] = useState(true);
  useEffect(() => {
    fetch("/api/v1/public/features")
      .then((r) => (r.ok ? r.json() : null))
      .then((f: { whatsapp?: boolean; signup?: boolean } | null) => {
        if (f?.signup === false) setSignup(false);
        if (f?.whatsapp === false) {
          setWhatsapp(false);
          setMode("password");
        }
      })
      .catch(() => undefined);
  }, []);

  if (me) return <Navigate to={homeFor(me)} replace />;

  async function submit(e: FormEvent, orgSlug?: string) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(identifier, password, orgSlug);
      nav("/", { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.code === "choose_organization") {
        setOrgs(err.details as { slug: string; name: string }[]);
      } else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function sendLink(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/auth/magic-link", { method: "POST", body: { phone } });
      setSent(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const switcher = !whatsapp ? (
    <span className="text-sm text-ink-2" data-testid="ask-admin">{t("auth.askAdmin")}</span>
  ) : (
    <button type="button" className="text-sm font-medium text-brand underline-offset-2 hover:underline"
      onClick={() => { setMode(mode === "link" ? "password" : "link"); setError(null); setSent(false); }}>
      {mode === "link" ? t("auth.orPassword") : t("auth.orWhatsApp")}
    </button>
  );

  if (mode === "link") {
    return (
      <AuthShell>
        <h1 className="text-2xl font-semibold tracking-tight">{t("auth.signIn")}</h1>
        <p className="mt-1 text-sm text-ink-2">{t("app.tagline")}</p>
        <form onSubmit={sendLink} className="mt-8 space-y-4">
          {error && <Alert>{error}</Alert>}
          {sent ? (
            <Alert tone="ok">{t("auth.linkSent")}</Alert>
          ) : (
            <>
              <Field label={t("auth.phone")}>
                {(id) => <Input id={id} type="tel" inputMode="tel" autoComplete="tel" required value={phone} onChange={(e) => setPhone(e.target.value)} autoFocus />}
              </Field>
              <Button type="submit" size="lg" className="w-full" busy={busy}>{t("auth.sendLink")}</Button>
            </>
          )}
        </form>
        <p className="mt-6">{switcher}</p>
      </AuthShell>
    );
  }

  return (
    <AuthShell>
      <h1 className="text-2xl font-semibold tracking-tight">{t("auth.signIn")}</h1>
      <p className="mt-1 text-sm text-ink-2">{t("app.tagline")}</p>
      <form onSubmit={(e) => submit(e)} className="mt-8 space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label={t("auth.identifier")}>
          {(id) => (
            <Input id={id} autoComplete="username" inputMode="email" required value={identifier}
              onChange={(e) => setIdentifier(e.target.value)} autoFocus />
          )}
        </Field>
        <Field label={t("auth.password")}>
          {(id) => (
            <Input id={id} type="password" autoComplete="current-password" required value={password}
              onChange={(e) => setPassword(e.target.value)} />
          )}
        </Field>
        {orgs ? (
          <div className="space-y-2">
            <p className="text-sm text-ink-2">{t("auth.chooseOrg")}</p>
            {orgs.map((o) => (
              <Button key={o.slug} type="button" variant="secondary" className="w-full justify-start"
                busy={busy} onClick={(e) => submit(e, o.slug)}>
                {o.name}
              </Button>
            ))}
          </div>
        ) : (
          <Button type="submit" size="lg" className="w-full" busy={busy}>
            {busy ? t("auth.signingIn") : t("auth.signIn")}
          </Button>
        )}
      </form>
      <p className="mt-6">{switcher}</p>
      {signup && (
        <p className="mt-3 text-sm text-ink-2">
          {t("auth.noAccount")}{" "}
          <Link to="/signup" className="font-medium text-brand underline-offset-2 hover:underline">
            {t("auth.createOrg")}
          </Link>
        </p>
      )}
    </AuthShell>
  );
}

export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_minmax(420px,520px)]">
      <aside className="relative hidden overflow-hidden bg-brand p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <Wordmark light />
        <div className="max-w-md">
          {/* A register page, struck through: the product in one image. */}
          <div className="mb-10 space-y-3 font-mono text-sm text-white/40">
            {["14:02  R. Das       Infosys    Mtg   ✎", "14:05  S. Mishra    TCS        Intv  ✎", "14:09  —  illegible  —        ✎"].map((l) => (
              <div key={l} className="relative whitespace-pre">
                {l}
                <span className="absolute inset-x-0 top-1/2 h-px bg-accent/80" />
              </div>
            ))}
          </div>
          <p className="text-3xl font-semibold leading-tight">Visitors check in from their own phone in under a minute.</p>
          <p className="mt-4 text-white/70">Hosts approve on WhatsApp. Guards see who is on site, live. No hardware, no app installs.</p>
        </div>
        <p className="text-xs text-white/50">Data stored in India · DPDP Act 2023 ready</p>
      </aside>
      <main className="flex flex-col px-4 py-8 sm:px-10">
        <div className="flex items-center justify-between">
          <span className="lg:invisible"><Wordmark /></span>
          <LanguageSwitch />
        </div>
        <div className="mx-auto flex w-full max-w-sm flex-1 flex-col justify-center py-10">{children}</div>
      </main>
    </div>
  );
}

export function Wordmark({ light }: { light?: boolean }) {
  return (
    <span className={`inline-flex items-center gap-2 font-semibold tracking-tight ${light ? "text-white" : "text-ink"}`}>
      <svg viewBox="0 0 24 24" className="size-6" aria-hidden>
        <rect x="2" y="2" width="20" height="20" rx="5" fill={light ? "#fff" : "var(--color-brand)"} />
        <path d="M7 12.5l3 3 7-7" stroke={light ? "var(--color-brand)" : "#fff"} strokeWidth="2.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      VMS
    </span>
  );
}
