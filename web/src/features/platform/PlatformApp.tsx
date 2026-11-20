import { useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { Alert, Badge, Button, Card, Dialog, Empty, Field, Input, PageHeader, Select, Spinner, cx, td, th } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Page } from "@/lib/types";
import { AuthShell, Wordmark } from "../auth/LoginPage";
import { useMut } from "../admin/queries";

/** Super-admin console: tenants, platform numbers and the shared WhatsApp line. English only. */

interface PlatformOrg {
  id: string;
  name: string;
  slug: string;
  status: "active" | "trial" | "suspended";
  data_region: string;
  created_at: string;
  user_count: number;
  site_count: number;
}
interface Stats { orgs: number; active_orgs: number; users: number; sites: number }
interface WhatsAppHealth {
  provider: string;
  phone_number_id: string | null;
  webhook_secret_set: boolean;
  template_prefix: string;
  last_24h: Record<string, number>;
  top_problems: { template: string; error: string | null; count: number }[];
  opted_out: number;
}

export function PlatformLogin() {
  const { acceptToken } = useAuth();
  const nav = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ access_token: string }>("/auth/platform/login", { method: "POST", body: { email, password } });
      await acceptToken(r.access_token);
      nav("/platform", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }
  return (
    <AuthShell>
      <h1 className="text-2xl font-semibold tracking-tight">Platform console</h1>
      <p className="mt-1 text-sm text-ink-2">For the people who run this VMS installation.</p>
      <form onSubmit={submit} className="mt-8 space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Email">{(id) => <Input id={id} type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />}</Field>
        <Field label="Password">{(id) => <Input id={id} type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />}</Field>
        <Button type="submit" size="lg" className="w-full" busy={busy}>Sign in</Button>
      </form>
    </AuthShell>
  );
}

export default function PlatformApp() {
  const { me, logout } = useAuth();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const { data: stats } = useQuery({ queryKey: ["platform", "stats"], queryFn: () => api<Stats>("/platform/stats") });
  const { data: orgs, isLoading } = useQuery({
    queryKey: ["platform", "orgs", q, status],
    queryFn: () => api<Page<PlatformOrg>>("/platform/orgs", { query: { q, status, limit: 200 } }),
    placeholderData: (p) => p,
  });
  const { data: wa } = useQuery({ queryKey: ["platform", "whatsapp"], queryFn: () => api<WhatsAppHealth>("/platform/whatsapp"), refetchInterval: 60_000 });

  return (
    <div className="min-h-dvh bg-paper">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-3"><Wordmark /><Badge tone="brand">Platform</Badge></div>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden text-ink-2 sm:inline">{me?.email}</span>
            <Button size="sm" variant="ghost" onClick={() => void logout()}>Sign out</Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <PageHeader title="Organizations" description="Every tenant on this installation. Suspending one blocks its staff and its check-in QR codes until you reactivate it." actions={<Button onClick={() => setCreating(true)}>New organization</Button>} />
        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          {[["Organizations", stats?.orgs], ["Active", stats?.active_orgs], ["Active staff", stats?.users], ["Sites", stats?.sites]].map(([label, value]) => (
            <div key={label as string} className="rounded-lg border border-line bg-surface px-4 py-3">
              <p className="text-xs text-ink-3">{label}</p>
              <p className="text-2xl font-semibold tabular-nums">{value ?? "–"}</p>
            </div>
          ))}
        </div>
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_320px]">
          <Card padded={false} title="Tenants" actions={
            <div className="flex gap-2">
              <Input aria-label="Search" placeholder="Search by name" className="w-48!" value={q} onChange={(e) => setQ(e.target.value)} />
              <Select aria-label="Status" className="w-32!" value={status} onChange={(e) => setStatus(e.target.value)}>
                <option value="">All</option><option value="active">Active</option><option value="trial">Trial</option><option value="suspended">Suspended</option>
              </Select>
            </div>}>
            {isLoading ? <Spinner /> : !orgs?.items.length ? <Empty title="No organizations">Create one, or let customers sign up themselves at /signup.</Empty> : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px]">
                  <thead className="border-b border-line"><tr><th className={th}>Organization</th><th className={th}>Status</th><th className={th}>Staff</th><th className={th}>Sites</th><th className={th}>Created</th><th className={th} /></tr></thead>
                  <tbody className="divide-y divide-line">{orgs.items.map((o) => <OrgRow key={o.id} o={o} />)}</tbody>
                </table>
              </div>
            )}
          </Card>
          <WhatsAppCard wa={wa} />
        </div>
      </main>
      <CreateOrgDialog open={creating} onClose={() => setCreating(false)} />
    </div>
  );
}

function OrgRow({ o }: { o: PlatformOrg }) {
  const toggle = useMut(() => api(`/platform/orgs/${o.id}/${o.status === "suspended" ? "reactivate" : "suspend"}`, { method: "POST" }), [["platform"]]);
  return (
    <tr>
      <td className={td}><span className="font-medium">{o.name}</span><span className="block text-xs text-ink-3">{o.slug} · {o.data_region}</span></td>
      <td className={td}><Badge tone={o.status === "active" ? "ok" : o.status === "trial" ? "brand" : "bad"}>{o.status}</Badge></td>
      <td className={cx(td, "tabular-nums")}>{o.user_count}</td>
      <td className={cx(td, "tabular-nums")}>{o.site_count}</td>
      <td className={td}>{new Date(o.created_at).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" })}</td>
      <td className={cx(td, "text-right")}>
        <Button size="sm" variant={o.status === "suspended" ? "secondary" : "ghost"} busy={toggle.isPending}
          onClick={() => (o.status !== "suspended" ? confirm(`Suspend ${o.name}? Its staff lose access and its QR codes stop working until you reactivate it.`) : true) && toggle.mutate(undefined)}>
          {o.status === "suspended" ? "Reactivate" : "Suspend"}
        </Button>
      </td>
    </tr>
  );
}

function WhatsAppCard({ wa }: { wa?: WhatsAppHealth }) {
  if (!wa) return <Card title="WhatsApp"><Spinner /></Card>;
  const sent = (wa.last_24h.sent ?? 0) + (wa.last_24h.delivered ?? 0) + (wa.last_24h.read ?? 0);
  const failed = wa.last_24h.failed ?? 0;
  const skipped = wa.last_24h.skipped ?? 0;
  const queued = wa.last_24h.queued ?? 0;
  return (
    <Card title="Shared WhatsApp number" className="self-start">
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div><dt className="text-ink-3">Provider</dt><dd className="font-medium">{wa.provider === "meta" ? "Meta Cloud API" : "Mock (dev inbox)"}</dd></div>
        <div><dt className="text-ink-3">Phone number ID</dt><dd className="truncate font-mono text-xs">{wa.phone_number_id ?? "—"}</dd></div>
        <div><dt className="text-ink-3">Webhook signature</dt><dd>{wa.webhook_secret_set ? "Verified" : <span className="text-bad">App secret not set</span>}</dd></div>
        <div><dt className="text-ink-3">Opted out (STOP)</dt><dd className="tabular-nums">{wa.opted_out}</dd></div>
      </dl>
      <p className="mt-4 text-xs font-medium uppercase tracking-wide text-ink-3">Last 24 hours</p>
      <div className="mt-2 grid grid-cols-4 gap-2 text-center text-sm">
        {[["Sent", sent], ["Queued", queued], ["Skipped", skipped], ["Failed", failed]].map(([l, n]) => (
          <div key={l as string} className="rounded-md bg-paper py-2"><p className="text-lg font-semibold tabular-nums">{n}</p><p className="text-xs text-ink-3">{l}</p></div>
        ))}
      </div>
      {wa.top_problems.length > 0 && (
        <ul className="mt-4 space-y-2 text-xs">
          {wa.top_problems.map((p, i) => (
            <li key={i} className="rounded-md border border-line px-3 py-2"><span className="font-medium">{p.template}</span> × {p.count}<span className="block break-words text-ink-2">{p.error ?? "—"}</span></li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-xs text-ink-3">Templates are named {wa.template_prefix}*. Check approval with <code>python -m scripts.whatsapp_templates status</code>.</p>
    </Card>
  );
}

function CreateOrgDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const blank = { name: "", admin_name: "", admin_email: "", admin_password: "", status: "trial", data_region: "ap-south-1" };
  const [f, setF] = useState(blank);
  const [error, setError] = useState<string | null>(null);
  const create = useMut(() => api("/platform/orgs", { method: "POST", body: f }), [["platform"]]);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Dialog open={open} onClose={onClose} title="New organization"
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button type="submit" form="new-org" busy={create.isPending}>Create</Button></>}>
      <form id="new-org" className="space-y-4" onSubmit={(e) => { e.preventDefault(); setError(null); create.mutate(undefined, { onSuccess: () => { setF(blank); onClose(); }, onError: (err) => setError(errorMessage(err)) }); }}>
        {error && <Alert>{error}</Alert>}
        <Field label="Organization name">{(i) => <Input id={i} required value={f.name} onChange={set("name")} />}</Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="First admin's name">{(i) => <Input id={i} required value={f.admin_name} onChange={set("admin_name")} />}</Field>
          <Field label="Admin email">{(i) => <Input id={i} type="email" required value={f.admin_email} onChange={set("admin_email")} />}</Field>
          <Field label="Initial password" hint="At least 10 characters. Ask them to change it.">{(i) => <Input id={i} type="password" required minLength={10} autoComplete="new-password" value={f.admin_password} onChange={set("admin_password")} />}</Field>
          <Field label="Status">{(i) => <Select id={i} value={f.status} onChange={set("status")}><option value="trial">Trial</option><option value="active">Active</option></Select>}</Field>
        </div>
        <Field label="Data region" hint="Where this org's data and files are stored.">{(i) => <Input id={i} required value={f.data_region} onChange={set("data_region")} />}</Field>
      </form>
    </Dialog>
  );
}
