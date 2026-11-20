import { useState, type FormEvent } from "react";
import { Alert, Badge, Button, Card, Checkbox, Dialog, Empty, Field, Input, PageHeader, Select, Spinner } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import type { CustomField, FieldType, Purpose } from "@/lib/types";
import { keys, useFields, useMut, usePurposes, useSites } from "./queries";

const TYPE_LABEL: Record<FieldType, string> = {
  text: "Short text",
  number: "Number",
  select: "Dropdown",
  checkbox: "Yes / no",
  declaration: "Declaration (must accept)",
};

export default function FormConfigPage() {
  return (
    <>
      <PageHeader
        title="Check-in form"
        description="Name, mobile number, company, photo and host are always asked. Add what your sites need on top. Keep it short: every extra field slows the queue."
      />
      <div className="grid gap-6 lg:grid-cols-2">
        <PurposesCard />
        <FieldsCard />
      </div>
    </>
  );
}

function move<T>(arr: T[], i: number, d: -1 | 1): T[] {
  const j = i + d;
  if (j < 0 || j >= arr.length) return arr;
  const c = [...arr];
  [c[i], c[j]] = [c[j], c[i]];
  return c;
}

function PurposesCard() {
  const { data, isLoading } = usePurposes();
  const [label, setLabel] = useState("");
  const [hi, setHi] = useState("");
  const [error, setError] = useState<string | null>(null);
  const add = useMut((b: object) => api("/purposes", { method: "POST", body: b }), [keys.purposes]);
  const reorder = useMut((ids: string[]) => api("/purposes/order", { method: "PUT", body: { ids } }), [keys.purposes]);
  const toggle = useMut((p: Purpose) => api(`/purposes/${p.id}`, { method: "PATCH", body: { is_active: !p.is_active } }), [keys.purposes]);
  const idProof = useMut((p: Purpose) => api(`/purposes/${p.id}`, { method: "PATCH", body: { requires_id_proof: !p.requires_id_proof } }), [keys.purposes]);

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    add.mutate(
      { label, label_i18n: hi ? { hi } : {} },
      { onSuccess: () => { setLabel(""); setHi(""); }, onError: (err) => setError(errorMessage(err)) },
    );
  }

  return (
    <Card title="Purpose of visit" padded={false}>
      {isLoading ? <Spinner /> : (
        <ul className="divide-y divide-line">
          {data?.map((p, i) => (
            <li key={p.id} className={`flex items-center gap-3 px-5 py-2.5 ${p.is_active ? "" : "opacity-50"}`}>
              <div className="flex flex-col">
                <button className="text-ink-3 hover:text-ink disabled:opacity-30" aria-label="Move up" disabled={i === 0}
                  onClick={() => reorder.mutate(move(data, i, -1).map((x) => x.id))}>▲</button>
                <button className="text-ink-3 hover:text-ink disabled:opacity-30" aria-label="Move down" disabled={i === data.length - 1}
                  onClick={() => reorder.mutate(move(data, i, 1).map((x) => x.id))}>▼</button>
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{p.label}</p>
                {p.label_i18n.hi && <p className="text-xs text-ink-3">{p.label_i18n.hi}</p>}
              </div>
              <button onClick={() => idProof.mutate(p)} title="Ask for ID proof when this purpose is chosen">
                <Badge tone={p.requires_id_proof ? "warn" : "neutral"}>{p.requires_id_proof ? "ID required" : "No ID"}</Badge>
              </button>
              <Button size="sm" variant="ghost" onClick={() => toggle.mutate(p)}>{p.is_active ? "Hide" : "Show"}</Button>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="space-y-3 border-t border-line p-5">
        {error && <Alert>{error}</Alert>}
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Input required placeholder="New purpose, e.g. Audit" value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Purpose (English)" />
          <Input placeholder="हिन्दी (optional)" value={hi} onChange={(e) => setHi(e.target.value)} aria-label="Purpose (Hindi)" lang="hi" />
        </div>
        <Button type="submit" size="sm" busy={add.isPending}>Add purpose</Button>
      </form>
    </Card>
  );
}

function FieldsCard() {
  const { data, isLoading } = useFields();
  const { data: sites } = useSites();
  const [adding, setAdding] = useState(false);
  const reorder = useMut((ids: string[]) => api("/custom-fields/order", { method: "PUT", body: { ids } }), [keys.fields]);
  const toggle = useMut((f: CustomField) => api(`/custom-fields/${f.id}`, { method: "PATCH", body: { is_active: !f.is_active } }), [keys.fields]);
  const siteName = (id: string | null) => (id ? sites?.find((s) => s.id === id)?.name ?? "Site" : "All sites");

  return (
    <Card title="Extra fields" actions={<Button size="sm" variant="secondary" onClick={() => setAdding(true)}>Add field</Button>} padded={false}>
      {isLoading ? <Spinner /> : !data?.length ? (
        <Empty title="No extra fields">For example: laptop serial number for IT parks, or a PPE acknowledgement for plants.</Empty>
      ) : (
        <ul className="divide-y divide-line">
          {data.map((f, i) => (
            <li key={f.id} className={`flex items-center gap-3 px-5 py-2.5 ${f.is_active ? "" : "opacity-50"}`}>
              <div className="flex flex-col">
                <button className="text-ink-3 hover:text-ink disabled:opacity-30" aria-label="Move up" disabled={i === 0}
                  onClick={() => reorder.mutate(move(data, i, -1).map((x) => x.id))}>▲</button>
                <button className="text-ink-3 hover:text-ink disabled:opacity-30" aria-label="Move down" disabled={i === data.length - 1}
                  onClick={() => reorder.mutate(move(data, i, 1).map((x) => x.id))}>▼</button>
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium">{f.label} {f.required && <span className="text-bad">*</span>}</p>
                <p className="text-xs text-ink-3">{TYPE_LABEL[f.type]} · {siteName(f.site_id)} · <code className="font-mono">{f.key}</code></p>
              </div>
              <Button size="sm" variant="ghost" onClick={() => toggle.mutate(f)}>{f.is_active ? "Hide" : "Show"}</Button>
            </li>
          ))}
        </ul>
      )}
      <FieldDialog open={adding} onClose={() => setAdding(false)} />
    </Card>
  );
}

function slug(s: string) {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").replace(/^(\d)/, "f_$1").slice(0, 50);
}

function FieldDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { data: sites } = useSites();
  const empty = { label: "", hi: "", type: "text" as FieldType, options: "", required: false, site_id: "" };
  const [f, setF] = useState(empty);
  const [error, setError] = useState<string | null>(null);
  const add = useMut((b: object) => api("/custom-fields", { method: "POST", body: b }), [keys.fields]);

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    add.mutate(
      {
        key: slug(f.label) || "field",
        label: f.label,
        label_i18n: f.hi ? { hi: f.hi } : {},
        type: f.type,
        options: f.type === "select" ? f.options.split("\n").map((s) => s.trim()).filter(Boolean) : [],
        required: f.required,
        site_id: f.site_id || null,
      },
      { onSuccess: () => { setF(empty); onClose(); }, onError: (err) => setError(errorMessage(err)) },
    );
  }

  return (
    <Dialog open={open} onClose={onClose} title="Add field">
      <form onSubmit={submit} className="space-y-4">
        {error && <Alert>{error}</Alert>}
        <Field label="Question / label">{(i) => <Input id={i} required value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} placeholder="Laptop serial number" />}</Field>
        <Field label="Hindi label" hint="Optional. Shown when the visitor picks हिन्दी.">{(i) => <Input id={i} lang="hi" value={f.hi} onChange={(e) => setF({ ...f, hi: e.target.value })} />}</Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Type">
            {(i) => (
              <Select id={i} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value as FieldType })}>
                {Object.entries(TYPE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Applies to">
            {(i) => (
              <Select id={i} value={f.site_id} onChange={(e) => setF({ ...f, site_id: e.target.value })}>
                <option value="">All sites</option>
                {sites?.filter((s) => s.is_active).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
            )}
          </Field>
        </div>
        {f.type === "select" && (
          <Field label="Options" hint="One per line.">
            {(i) => (
              <textarea id={i} rows={4} required value={f.options} onChange={(e) => setF({ ...f, options: e.target.value })}
                className="block w-full rounded-lg border border-line-strong bg-surface px-3 py-2 text-base sm:text-sm focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20" />
            )}
          </Field>
        )}
        {f.type === "declaration" ? (
          <p className="text-xs text-ink-3">Visitors must tick this to continue. Their acceptance is stored with the visit.</p>
        ) : (
          <Checkbox label="Required" checked={f.required} onChange={(e) => setF({ ...f, required: e.target.checked })} />
        )}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" busy={add.isPending}>Add field</Button>
        </div>
      </form>
    </Dialog>
  );
}
