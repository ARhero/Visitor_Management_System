import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { Alert, Button, Field, Input } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { AuthShell } from "./LoginPage";

export default function SignupPage() {
  const { acceptToken } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({ org_name: "", admin_name: "", email: "", phone: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ access_token: string }>("/auth/signup", {
        method: "POST",
        body: { ...f, phone: f.phone || undefined },
      });
      await acceptToken(r.access_token);
      nav("/admin/setup", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell>
      <h1 className="text-2xl font-semibold tracking-tight">Set up your organization</h1>
      <p className="mt-1 text-sm text-ink-2">Takes two minutes. You can add sites and hosts next.</p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Organization name">{(id) => <Input id={id} required value={f.org_name} onChange={set("org_name")} autoFocus />}</Field>
        <Field label="Your name">{(id) => <Input id={id} required autoComplete="name" value={f.admin_name} onChange={set("admin_name")} />}</Field>
        <Field label="Work email">{(id) => <Input id={id} type="email" required autoComplete="email" value={f.email} onChange={set("email")} />}</Field>
        <Field label="Mobile number" hint="Optional. Add it to receive visitor approvals on WhatsApp yourself.">
          {(id) => <Input id={id} type="tel" inputMode="tel" autoComplete="tel" placeholder="98765 43210" value={f.phone} onChange={set("phone")} />}
        </Field>
        <Field label="Password" hint="At least 10 characters.">
          {(id) => <Input id={id} type="password" required minLength={10} autoComplete="new-password" value={f.password} onChange={set("password")} />}
        </Field>
        <Button type="submit" size="lg" className="w-full" busy={busy}>Create organization</Button>
      </form>
      <p className="mt-6 text-sm text-ink-2">
        Already registered? <Link to="/login" className="font-medium text-brand hover:underline">Sign in</Link>
      </p>
    </AuthShell>
  );
}
