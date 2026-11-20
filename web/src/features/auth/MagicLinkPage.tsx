import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router";
import { Alert, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AuthShell } from "./LoginPage";

/** Landing page of the WhatsApp sign-in link: trade the one-time token for a session. */
export default function MagicLinkPage() {
  const { token = "" } = useParams();
  const { t } = useTranslation();
  const { acceptToken, loading } = useAuth();
  const nav = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const once = useRef(false); // StrictMode runs effects twice; the link works only once

  useEffect(() => {
    // Wait for the start-up session check: if someone else is signed in on this browser,
    // their refresh must not land after (and overwrite) the session from this link.
    if (loading || once.current) return;
    once.current = true;
    (async () => {
      try {
        const r = await api<{ access_token: string }>("/auth/magic", { method: "POST", body: { token } });
        await acceptToken(r.access_token);
        nav("/", { replace: true });
      } catch (e) {
        setError(errorMessage(e));
      }
    })();
  }, [token, acceptToken, nav, loading]);

  return (
    <AuthShell>
      {error ? (
        <div className="space-y-4">
          <Alert>{error}</Alert>
          <Link to="/login?link=1" className="font-medium text-brand hover:underline">{t("auth.orWhatsApp")}</Link>
        </div>
      ) : (
        <Spinner label={t("auth.signingIn")} />
      )}
    </AuthShell>
  );
}
