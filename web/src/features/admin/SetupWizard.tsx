import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { Alert, Badge, Button, Card, Checkbox, Field, Input, Select, Spinner, cx } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Org, OrgSettings, Purpose } from "@/lib/types";
import { ImportDialog } from "./ImportDialog";
import { LogoUpload } from "./LogoUpload";
import { type Checklist, useChecklist } from "./onboardingApi";
import { keys, useMut, useOrg, usePurposes, useSites, useUsers } from "./queries";
import { PosterButton } from "./SitesPage";

/** Self-serve setup: organization → first site → hosts → check-in form → posters → test visit. */


const STEPS = ["org", "site", "hosts", "form", "posters", "test_visit"] as const;
type StepKey = (typeof STEPS)[number];

export default function SetupWizard() {
  const [params, setParams] = useSearchParams();
  const { data: checklist } = useChecklist();
  const { data: org } = useOrg();
  const qc = useQueryClient();
  const firstOpen = checklist?.steps.find((s) => s.wizard && !s.done)?.key as StepKey | undefined;
  const current = (params.get("step") as StepKey | null) ?? firstOpen ?? "org";
  const index = STEPS.indexOf(current);
  const go = (k: StepKey) => setParams({ step: k }, { replace: false });
  const next = () => {
    void qc.invalidateQueries({ queryKey: ["onboarding"] });
    if (index < STEPS.length - 1) go(STEPS[index + 1]);
  };

  if (!checklist || !org) return <Spinner />;
  const byKey = Object.fromEntries(checklist.steps.map((s) => [s.key, s]));
  const wizardDone = STEPS.filter((k) => byKey[k]?.done).length;

  return (
    <div className="mx-auto max-w-5xl">
      <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-sm text-ink-3">Setup · {wizardDone} of {STEPS.length} done</p>
          <h1 className="text-2xl font-semibold tracking-tight">Get {org.name} ready for visitors</h1>
        </div>
        <Link to="/admin" className="text-sm text-ink-2 hover:text-ink">Finish later →</Link>
      </div>
      <div className="grid gap-6 lg:grid-cols-[240px_minmax(0,1fr)]">
        <ol className="flex gap-1 overflow-x-auto pb-1 lg:block lg:space-y-1 lg:overflow-visible">
          {STEPS.map((k, i) => {
            const s = byKey[k];
            return (
              <li key={k} className="shrink-0">
                <button onClick={() => go(k)} aria-current={k === current ? "step" : undefined}
                  className={cx("flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm",
                    k === current ? "bg-brand-50 font-medium text-brand" : "text-ink-2 hover:bg-ink/5")}>
                  <span className={cx("grid size-6 shrink-0 place-items-center rounded-full border text-xs font-semibold",
                    s?.done ? "border-brand bg-brand text-white" : "border-line-strong text-ink-3")}>
                    {s?.done ? "✓" : i + 1}
                  </span>
                  <span className="whitespace-nowrap lg:whitespace-normal">{s?.label}</span>
                </button>
              </li>
            );
          })}
        </ol>
        <div>
          {current === "org" && <OrgStep org={org} onDone={next} />}
          {current === "site" && <SiteStep onDone={next} />}
          {current === "hosts" && <HostsStep onDone={next} />}
          {current === "form" && <FormStep org={org} onDone={next} />}
          {current === "posters" && <PostersStep done={!!byKey.posters?.done} onDone={next} />}
          {current === "test_visit" && <TestStep checklist={checklist} />}
        </div>
      </div>
    </div>
  );
}

function StepCard({ title, intro, children, footer }: { title: string; intro: ReactNode; children: ReactNode; footer?: ReactNode }) {
  return (
    <Card>
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-ink-2">{intro}</p>
      <div className="mt-6">{children}</div>
      {footer && <div className="mt-6 flex flex-wrap items-center justify-end gap-3 border-t border-line pt-4">{footer}</div>}
    </Card>
  );
}

const complete = (step: "org" | "form" | "posters") => api("/onboarding/complete", { method: "POST", body: { step } });

function OrgStep({ org, onDone }: { org: Org; onDone: () => void }) {
  const [name, setName] = useState(org.name);
  const [brand, setBrand] = useState(org.branding);
  const [locale, setLocale] = useState(org.default_locale);
  const [contact, setContact] = useState(org.settings.privacy_contact ?? "");
  const [error, setError] = useState<string | null>(null);
  const save = useMut(async () => {
    await api<Org>("/org", {
      method: "PATCH",
      body: { name, default_locale: locale, branding: brand, settings: { ...org.settings, auto_checkout_time: org.settings.auto_checkout_time.slice(0, 5), privacy_contact: contact || null } },
    });
    await complete("org");
  }, [keys.org, ["onboarding"]]);
  return (
    <form onSubmit={(e) => { e.preventDefault(); setError(null); save.mutate(undefined, { onSuccess: onDone, onError: (err) => setError(errorMessage(err)) }); }}>
      <StepCard title="Your organization" intro="Visitors see this name, logo and colour on the check-in page, their pass and your QR posters."
        footer={<Button type="submit" busy={save.isPending}>Save and continue</Button>}>
        {error && <div className="mb-4"><Alert>{error}</Alert></div>}
        <LogoUpload org={org} />
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field label="Organization name">{(i) => <Input id={i} required value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <Field label="Visitors see the check-in page in" hint="They can switch language themselves.">
            {(i) => (
              <Select id={i} value={locale} onChange={(e) => setLocale(e.target.value)}>
                <option value="en">English</option>
                <option value="hi">हिन्दी (Hindi)</option>
              </Select>
            )}
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Brand colour">{(i) => <Input id={i} type="color" className="p-1" value={brand.primary_color} onChange={(e) => setBrand({ ...brand, primary_color: e.target.value })} />}</Field>
            <Field label="Accent">{(i) => <Input id={i} type="color" className="p-1" value={brand.accent_color} onChange={(e) => setBrand({ ...brand, accent_color: e.target.value })} />}</Field>
          </div>
          <Field label="Privacy contact" hint="Email or phone for questions about visitor data (DPDP Act).">
            {(i) => <Input id={i} maxLength={200} placeholder="privacy@yourcompany.in" value={contact} onChange={(e) => setContact(e.target.value)} />}
          </Field>
        </div>
      </StepCard>
    </form>
  );
}

function SiteStep({ onDone }: { onDone: () => void }) {
  const { data: sites } = useSites();
  const [f, setF] = useState({ name: "", city: "", address: "", default_gate_name: "Main Gate" });
  const [error, setError] = useState<string | null>(null);
  const create = useMut(
    () => api("/sites", { method: "POST", body: { name: f.name, city: f.city || null, address: f.address || null, default_gate_name: f.default_gate_name || "Main Gate" } }),
    [keys.sites, ["onboarding"]],
  );
  const active = (sites ?? []).filter((s) => s.is_active);
  if (!sites) return <Spinner />;
  if (active.length) {
    return (
      <StepCard title="Sites and gates" intro="Each gate gets its own QR poster, so you can see which entrance visitors used."
        footer={<Button onClick={onDone}>Continue</Button>}>
        <ul className="divide-y divide-line rounded-lg border border-line">
          {active.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm">
              <span><span className="font-medium">{s.name}</span>{s.city ? <span className="text-ink-3"> · {s.city}</span> : null}</span>
              <span className="text-ink-2">{s.gates.filter((g) => g.is_active).map((g) => g.name).join(", ") || "No gates"}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-sm text-ink-2">More sites, gates and safety contacts: <Link to="/admin/sites" className="text-brand hover:underline">Sites & gates</Link>.</p>
      </StepCard>
    );
  }
  return (
    <form onSubmit={(e: FormEvent) => { e.preventDefault(); setError(null); create.mutate(undefined, { onSuccess: onDone, onError: (err) => setError(errorMessage(err)) }); }}>
      <StepCard title="Add your first site" intro="An office, plant or campus. You can add more later."
        footer={<Button type="submit" busy={create.isPending}>Add site and continue</Button>}>
        {error && <div className="mb-4"><Alert>{error}</Alert></div>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Site name">{(i) => <Input id={i} required autoFocus placeholder="Bhubaneswar HQ" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />}</Field>
          <Field label="City">{(i) => <Input id={i} value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} />}</Field>
          <Field label="Address" hint="Shown on invitations, with directions.">{(i) => <Input id={i} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} />}</Field>
          <Field label="First gate" hint="Reception, Gate 1, Loading bay…">{(i) => <Input id={i} required value={f.default_gate_name} onChange={(e) => setF({ ...f, default_gate_name: e.target.value })} />}</Field>
        </div>
      </StepCard>
    </form>
  );
}

function HostsStep({ onDone }: { onDone: () => void }) {
  const { data: hosts } = useUsers({ role: "host", limit: 8 });
  const [importing, setImporting] = useState(false);
  const [f, setF] = useState({ full_name: "", phone: "" });
  const [error, setError] = useState<string | null>(null);
  const add = useMut(() => api("/users", { method: "POST", body: { full_name: f.full_name, phone: f.phone, roles: ["host"] } }), [["users"], ["onboarding"]]);
  return (
    <StepCard title="Your hosts" intro="The people visitors come to see. They approve visitors on WhatsApp, so each needs a mobile number. No app or password needed."
      footer={<><Button variant="ghost" onClick={onDone}>Skip for now</Button><Button onClick={onDone} disabled={!hosts?.total}>Continue</Button></>}>
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-paper p-4">
        <div className="min-w-0 flex-1 text-sm">
          <p className="font-medium">Import from a spreadsheet</p>
          <p className="text-ink-2">CSV with name, mobile, email, department. Re-importing updates people, matched by mobile number.</p>
        </div>
        <Button variant="secondary" onClick={() => setImporting(true)}>Import CSV</Button>
      </div>
      <form className="mt-5" onSubmit={(e) => { e.preventDefault(); setError(null); add.mutate(undefined, { onSuccess: () => setF({ full_name: "", phone: "" }), onError: (err) => setError(errorMessage(err)) }); }}>
        <p className="mb-2 text-sm font-medium">Or add one person</p>
        {error && <div className="mb-3"><Alert>{error}</Alert></div>}
        <div className="flex flex-wrap items-end gap-2">
          <Input aria-label="Name" required placeholder="Name" className="w-56!" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
          <Input aria-label="Mobile number" required type="tel" placeholder="98765 43210" className="w-44!" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
          <Button type="submit" variant="secondary" busy={add.isPending}>Add host</Button>
        </div>
      </form>
      {hosts && hosts.total > 0 && (
        <div className="mt-5">
          <p className="mb-2 text-sm text-ink-2">{hosts.total} host{hosts.total === 1 ? "" : "s"} so far</p>
          <ul className="flex flex-wrap gap-2">
            {hosts.items.map((u) => <li key={u.id}><Badge>{u.full_name}</Badge></li>)}
            {hosts.total > hosts.items.length && <li className="text-sm text-ink-3">+{hosts.total - hosts.items.length} more</li>}
          </ul>
        </div>
      )}
      <ImportDialog open={importing} onClose={() => setImporting(false)} />
    </StepCard>
  );
}

function FormStep({ org, onDone }: { org: Org; onDone: () => void }) {
  const { data: purposes } = usePurposes();
  const [s, setS] = useState<OrgSettings>(org.settings);
  const [label, setLabel] = useState("");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setS(org.settings), [org.settings]);
  const addPurpose = useMut(() => api("/purposes", { method: "POST", body: { label } }), [keys.purposes]);
  const togglePurpose = useMut((p: Purpose) => api(`/purposes/${p.id}`, { method: "PATCH", body: { is_active: !p.is_active } }), [keys.purposes]);
  const save = useMut(async () => {
    await api("/org", { method: "PATCH", body: { settings: { ...s, auto_checkout_time: s.auto_checkout_time.slice(0, 5) } } });
    await complete("form");
  }, [keys.org, ["onboarding"]]);
  return (
    <StepCard title="The check-in form" intro="Keep it short: visitors should be through in under a minute. Name, mobile number (verified on WhatsApp) and host are always asked."
      footer={<Button busy={save.isPending} onClick={() => { setError(null); save.mutate(undefined, { onSuccess: onDone, onError: (err) => setError(errorMessage(err)) }); }}>Save and continue</Button>}>
      {error && <div className="mb-4"><Alert>{error}</Alert></div>}
      <div className="grid gap-6 md:grid-cols-2">
        <div className="space-y-4">
          <Checkbox label="Take a live selfie" hint="Recommended. Guards match the face at the gate." checked={s.require_selfie} onChange={(e) => setS({ ...s, require_selfie: e.target.checked })} />
          <Field label="ID proof" hint="Only the ID type and its last 4 characters are ever stored. Never a full Aadhaar number.">
            {(i) => (
              <Select id={i} value={s.id_proof_mode} onChange={(e) => setS({ ...s, id_proof_mode: e.target.value as OrgSettings["id_proof_mode"] })}>
                <option value="off">Don't ask</option>
                <option value="optional">Ask, optional</option>
                <option value="required">Required (e.g. government sites)</option>
              </Select>
            )}
          </Field>
          <p className="text-sm text-ink-2">Need a laptop serial, PPE acknowledgement or NDA? Add extra fields under <Link to="/admin/form" className="text-brand hover:underline">Check-in form</Link>.</p>
        </div>
        <div>
          <p className="mb-2 text-sm font-medium">Purposes of visit</p>
          <ul className="divide-y divide-line rounded-lg border border-line">
            {(purposes ?? []).map((p) => (
              <li key={p.id} className="flex items-center justify-between px-3 py-2 text-sm">
                <span className={cx(!p.is_active && "text-ink-3 line-through")}>{p.label}</span>
                <button className="text-xs text-ink-3 hover:text-ink" onClick={() => togglePurpose.mutate(p)}>{p.is_active ? "Hide" : "Show"}</button>
              </li>
            ))}
          </ul>
          <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); addPurpose.mutate(undefined, { onSuccess: () => setLabel(""), onError: (err) => setError(errorMessage(err)) }); }}>
            <Input aria-label="New purpose" required placeholder="e.g. Vendor delivery" value={label} onChange={(e) => setLabel(e.target.value)} />
            <Button type="submit" variant="secondary" busy={addPurpose.isPending}>Add</Button>
          </form>
        </div>
      </div>
    </StepCard>
  );
}

function PostersStep({ done, onDone }: { done: boolean; onDone: () => void }) {
  const { data: sites } = useSites();
  const active = (sites ?? []).filter((s) => s.is_active && s.gates.some((g) => g.is_active));
  return (
    <StepCard title="Print the QR posters" intro="One A4 poster per gate, with your logo and colours. Print in colour and put it at reception at eye level, where visitors wait."
      footer={done ? <Button onClick={onDone}>Continue</Button> : <Button variant="ghost" onClick={onDone}>I'll print them later</Button>}>
      {!active.length ? <Alert tone="warn">Add a site with a gate first.</Alert> : (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {active.map((s) => (
            <li key={s.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-sm font-medium">{s.name}</span>
                <PosterButton path={`/sites/${s.id}/posters.pdf`} label={`All ${s.gates.filter((g) => g.is_active).length} poster(s)`} variant="secondary" />
              </div>
              <div className="mt-1 flex flex-wrap gap-x-1 text-sm text-ink-2">
                {s.gates.filter((g) => g.is_active).map((g) => <PosterButton key={g.id} path={`/gates/${g.id}/poster.pdf`} label={g.name} />)}
              </div>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-4 text-sm text-ink-2">Each poster also shows the check-in link, for visitors whose camera can't scan, and a line about how their data is used.</p>
    </StepCard>
  );
}

function TestStep({ checklist }: { checklist: Checklist }) {
  const { me } = useAuth();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [phone, setPhone] = useState(me?.phone ?? "");
  const [error, setError] = useState<string | null>(null);
  const test = checklist.test_visit;
  const waiting = test?.status === "pending" || test?.status === "waiting";
  useChecklist(waiting); // poll while the test is waiting for the tap
  const send = useMut(() => api("/onboarding/test-visit", { method: "POST", body: { phone: phone || undefined } }), [["onboarding"]]);
  useEffect(() => { void qc.invalidateQueries({ queryKey: ["onboarding"] }); }, [qc]);

  if (test && !waiting) {
    return (
      <StepCard title="You're ready for visitors" intro={test.status === "approved" ? "The test visit was approved on WhatsApp: requests reach your hosts and visitors get their pass. Scan your poster with a phone to try the visitor side too." : `The test visit ended as "${test.status}". You can send another one.`}
        footer={<><Button variant="ghost" onClick={() => send.mutate(undefined)}>Send another test</Button><Button onClick={() => nav("/admin")}>Go to the dashboard</Button></>}>
        <ul className="space-y-2 text-sm text-ink-2">
          <li>• Give guards a login under <Link to="/admin/people" className="text-brand hover:underline">People</Link>. They use the gate console on any phone.</li>
          <li>• Hosts can pre-approve guests from their phone: they sign in with a WhatsApp link, no password.</li>
          <li>• The test shows in your visit log as "Test visitor".</li>
        </ul>
      </StepCard>
    );
  }
  return (
    <form onSubmit={(e) => { e.preventDefault(); setError(null); send.mutate(undefined, { onError: (err) => setError(errorMessage(err)) }); }}>
      <StepCard title="Send yourself a test visit" intro="We'll send you the same WhatsApp message a host gets when a visitor arrives. Tap Approve on it to finish."
        footer={!waiting && <Button type="submit" busy={send.isPending}>Send test visit</Button>}>
        {error && <div className="mb-4"><Alert>{error}</Alert></div>}
        {waiting ? (
          <div className="flex items-start gap-3 rounded-lg border border-line bg-paper p-4 text-sm" role="status">
            <span className="mt-0.5 size-2.5 shrink-0 animate-pulse rounded-full bg-brand" />
            <div>
              <p className="font-medium">Waiting for you to tap Approve on WhatsApp…</p>
              <p className="mt-1 text-ink-2">Sent to {phone || me?.phone}. This page updates by itself.</p>
              {import.meta.env.DEV && <p className="mt-2"><a href="/dev/whatsapp" target="_blank" rel="noreferrer" className="text-brand hover:underline">Open the dev WhatsApp inbox →</a></p>}
            </div>
          </div>
        ) : (
          <Field label="Your WhatsApp number" hint="You'll also be able to receive visitors yourself.">
            {(i) => <Input id={i} type="tel" required inputMode="tel" placeholder="98765 43210" className="max-w-60" value={phone} onChange={(e) => setPhone(e.target.value)} />}
          </Field>
        )}
      </StepCard>
    </form>
  );
}
