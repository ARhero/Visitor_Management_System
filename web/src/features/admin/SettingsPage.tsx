import { useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { Alert, Button, Card, Checkbox, Empty, Field, Input, PageHeader, Select, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { Department, Org, OrgSettings } from "@/lib/types";
import { LogoUpload } from "./LogoUpload";
import { keys, useDepartments, useMut, useOrg } from "./queries";

export default function SettingsPage() {
  const { data: org, isLoading } = useOrg();
  return (
    <>
      <PageHeader title="Settings" description={org ? `${org.name} · data region ${org.data_region} · times shown in IST` : undefined} />
      {isLoading || !org ? <Spinner /> : (
        <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
          <div className="space-y-6">
            <OrgForm org={org} />
          </div>
          <DepartmentsCard />
        </div>
      )}
    </>
  );
}

function OrgForm({ org }: { org: Org }) {
  const whatsapp = useAuth().me?.whatsapp_enabled !== false;
  const [name, setName] = useState(org.name);
  const [s, setS] = useState<OrgSettings>(org.settings);
  const [brand, setBrand] = useState(org.branding);
  const [msg, setMsg] = useState<{ tone: "ok" | "bad"; text: string } | null>(null);
  const save = useMut((body: object) => api<Org>("/org", { method: "PATCH", body }), [keys.org]);
  useEffect(() => setS(org.settings), [org.settings]);

  const num = (k: keyof OrgSettings) => (e: React.ChangeEvent<HTMLInputElement>) => setS({ ...s, [k]: Number(e.target.value) });

  function submit(e: FormEvent) {
    e.preventDefault();
    setMsg(null);
    save.mutate(
      { name, settings: { ...s, auto_checkout_time: s.auto_checkout_time.slice(0, 5) }, branding: brand },
      { onSuccess: () => setMsg({ tone: "ok", text: "Saved" }), onError: (err) => setMsg({ tone: "bad", text: errorMessage(err) }) },
    );
  }

  return (
    <form onSubmit={submit} className="space-y-6">
      <Card title="Organization">
        <LogoUpload org={org} />
        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <Field label="Name">{(i) => <Input id={i} required value={name} onChange={(e) => setName(e.target.value)} />}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Brand colour">{(i) => <Input id={i} type="color" className="p-1" value={brand.primary_color} onChange={(e) => setBrand({ ...brand, primary_color: e.target.value })} />}</Field>
            <Field label="Accent">{(i) => <Input id={i} type="color" className="p-1" value={brand.accent_color} onChange={(e) => setBrand({ ...brand, accent_color: e.target.value })} />}</Field>
          </div>
        </div>
        <p className="mt-3 text-xs text-ink-3">Used on the visitor check-in page, the privacy page and QR posters.</p>
      </Card>

      <Card title="Approvals">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Escalate if the host hasn't answered in" hint="Minutes. Then the host's backup host is asked (set under People).">
            {(i) => <Input id={i} type="number" min={1} max={60} value={s.approval_timeout_min} onChange={num("approval_timeout_min")} />}
          </Field>
          <Field label="Escalation steps" hint="0 = never escalate.">
            {(i) => <Input id={i} type="number" min={0} max={5} value={s.max_escalations} onChange={num("max_escalations")} />}
          </Field>
          <Field label="Passes valid until / auto check-out at" hint="IST, daily. Every visitor pass works until this time on the day it was approved (approved within the last hour before it: 4 hours). Anyone still inside is checked out then.">
            {(i) => <Input id={i} type="time" value={s.auto_checkout_time.slice(0, 5)} onChange={(e) => setS({ ...s, auto_checkout_time: e.target.value })} />}
          </Field>
        </div>
      </Card>

      <Card title="Visitor identity">
        <div className="space-y-4">
          <Checkbox label="Require a live selfie" hint="Recommended. Guards match the face at the gate." checked={s.require_selfie} onChange={(e) => setS({ ...s, require_selfie: e.target.checked })} />
          <Field label="ID proof">
            {(i) => (
              <Select id={i} value={s.id_proof_mode} onChange={(e) => setS({ ...s, id_proof_mode: e.target.value as OrgSettings["id_proof_mode"] })}>
                <option value="off">Don't ask</option>
                <option value="optional">Ask, optional</option>
                <option value="required">Required (e.g. government sites)</option>
              </Select>
            )}
          </Field>
          {s.id_proof_mode !== "off" && (
            <Checkbox label="Store a photo of the ID" hint="Off by default. Aadhaar images are never stored; only ID type and last 4 digits are kept."
              checked={s.store_id_image} onChange={(e) => setS({ ...s, store_id_image: e.target.checked })} />
          )}
          {whatsapp ? (
            <>
              <Checkbox label="Visitors confirm their number with a WhatsApp code"
                hint="Off: the number is just typed in, and guards are told to check the visitor's ID."
                checked={s.verify_visitor_phone ?? true} onChange={(e) => setS({ ...s, verify_visitor_phone: e.target.checked })} />
              <Checkbox label="Guards must OTP-verify walk-ins they register" checked={s.guard_manual_requires_otp} onChange={(e) => setS({ ...s, guard_manual_requires_otp: e.target.checked })} />
            </>
          ) : (
            <p className="text-sm text-ink-2">
              WhatsApp is off on this system, so visitors type their number without a code and guards are told to check their ID.
              Hosts get visitor requests as phone alerts (they turn them on in the host app).
            </p>
          )}
        </div>
      </Card>

      <Card title="Privacy (DPDP Act)">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Delete visitor data after" hint="Days. Photos and personal details are purged; anonymous counts are kept for reports.">
            {(i) => <Input id={i} type="number" min={7} max={3650} className="max-w-40" value={s.retention_days} onChange={num("retention_days")} />}
          </Field>
          <Field label="Privacy contact" hint="Email or phone visitors can contact about their data. Shown in the privacy notice.">
            {(i) => <Input id={i} maxLength={200} placeholder="privacy@yourcompany.in" value={s.privacy_contact ?? ""} onChange={(e) => setS({ ...s, privacy_contact: e.target.value || null })} />}
          </Field>
        </div>
        <p className="mt-3 text-xs text-ink-3">Requests, look-ups, erasure and the notice text are under <Link to="/admin/privacy" className="text-brand hover:underline">Privacy</Link>.</p>
      </Card>

      <div className="sticky bottom-0 -mx-4 flex items-center justify-end gap-3 border-t border-line bg-paper/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-lg sm:border">
        {msg && <span className={`text-sm ${msg.tone === "ok" ? "text-ok" : "whitespace-pre-line text-bad"}`}>{msg.text}</span>}
        <Button type="submit" busy={save.isPending}>Save settings</Button>
      </div>
    </form>
  );
}

function DepartmentsCard() {
  const { data, isLoading } = useDepartments();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const add = useMut((n: string) => api("/departments", { method: "POST", body: { name: n } }), [keys.departments]);
  const del = useMut((d: Department) => api(`/departments/${d.id}`, { method: "DELETE" }), [keys.departments, ["users"]]);
  return (
    <Card title="Departments" padded={false} className="self-start">
      {isLoading ? <Spinner /> : !data?.length ? <Empty title="No departments">They are also created by CSV import.</Empty> : (
        <ul className="divide-y divide-line">
          {data.map((d) => (
            <li key={d.id} className="flex items-center justify-between px-5 py-2.5 text-sm">
              <span>{d.name} <span className="text-ink-3">· {d.user_count}</span></span>
              <button className="text-xs text-ink-3 hover:text-bad"
                onClick={() => confirm(`Delete ${d.name}?${d.user_count ? ` ${d.user_count} people will have no department.` : ""}`) && del.mutate(d)}>
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
      <form className="space-y-2 border-t border-line p-4"
        onSubmit={(e) => { e.preventDefault(); setError(null); add.mutate(name, { onSuccess: () => setName(""), onError: (err) => setError(errorMessage(err)) }); }}>
        {error && <Alert>{error}</Alert>}
        <div className="flex gap-2">
          <Input required placeholder="New department" value={name} onChange={(e) => setName(e.target.value)} aria-label="New department" />
          <Button type="submit" variant="secondary" busy={add.isPending}>Add</Button>
        </div>
      </form>
    </Card>
  );
}
