import { useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Alert, Badge, Button, Card, Dialog, Empty, Field, Input, PageHeader, Spinner, td, th } from "@/components/ui";
import { api, downloadFile, errorMessage } from "@/lib/api";
import type { Gate, Site } from "@/lib/types";
import { keys, useMut, useSites } from "./queries";

type SiteForm = Partial<Pick<Site, "name" | "address" | "city" | "state" | "pincode" | "map_url" | "directions_text" | "safety_contacts">>;

export default function SitesPage() {
  const { data: sites, isLoading } = useSites();
  const [editing, setEditing] = useState<Site | "new" | null>(null);
  const [addGateTo, setAddGateTo] = useState<Site | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const visible = (sites ?? []).filter((s) => showInactive || s.is_active);

  return (
    <>
      <PageHeader
        title="Sites & gates"
        description="Each gate gets its own QR poster. Visitors scan it at reception to check in."
        actions={
          <>
            <label className="flex items-center gap-2 text-sm text-ink-2">
              <input type="checkbox" className="accent-brand" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
              Show inactive
            </label>
            <Button onClick={() => setEditing("new")}>Add site</Button>
          </>
        }
      />
      {isLoading ? (
        <Spinner />
      ) : visible.length === 0 ? (
        <Card><Empty title="No sites yet">Add your first office, plant or campus to get a check-in QR code.</Empty></Card>
      ) : (
        <div className="space-y-5">
          {visible.map((s) => (
            <SiteCard key={s.id} site={s} onEdit={() => setEditing(s)} onAddGate={() => setAddGateTo(s)} />
          ))}
        </div>
      )}
      <SiteDialog site={editing} onClose={() => setEditing(null)} />
      <GateDialog site={addGateTo} onClose={() => setAddGateTo(null)} />
    </>
  );
}

function SiteCard({ site, onEdit, onAddGate }: { site: Site; onEdit: () => void; onAddGate: () => void }) {
  const deactivate = useMut(() => api(`/sites/${site.id}`, { method: "DELETE" }), [keys.sites]);
  const reactivate = useMut(() => api(`/sites/${site.id}`, { method: "PATCH", body: { is_active: true } }), [keys.sites]);
  const where = [site.address, site.city, site.state, site.pincode].filter(Boolean).join(", ");
  return (
    <Card
      padded={false}
      title={
        <span className="flex items-center gap-2">
          {site.name} {!site.is_active && <Badge>Inactive</Badge>}
        </span>
      }
      actions={
        <>
          <Button size="sm" variant="ghost" onClick={onEdit}>Edit</Button>
          {site.is_active ? (
            <>
              {site.gates.some((g) => g.is_active) && <PosterButton path={`/sites/${site.id}/posters.pdf`} label="All posters (PDF)" />}
              <Button size="sm" variant="secondary" onClick={onAddGate}>Add gate</Button>
              <Button size="sm" variant="ghost" busy={deactivate.isPending}
                onClick={() => confirm(`Deactivate ${site.name}? Its QR posters will stop working.`) && deactivate.mutate(undefined)}>
                Deactivate
              </Button>
            </>
          ) : (
            <Button size="sm" variant="secondary" busy={reactivate.isPending} onClick={() => reactivate.mutate(undefined)}>Reactivate</Button>
          )}
        </>
      }
    >
      {where && <p className="border-b border-line px-5 py-2.5 text-sm text-ink-2">{where}</p>}
      {site.gates.length === 0 ? (
        <Empty title="No gates">Add a gate to generate its QR code.</Empty>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px]">
            <thead className="border-b border-line">
              <tr><th className={th}>Gate</th><th className={th}>Check-in link</th><th className={th}>Status</th><th className={th} /></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {site.gates.map((g) => <GateRow key={g.id} gate={g} />)}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function GateRow({ gate }: { gate: Gate }) {
  const [copied, setCopied] = useState(false);
  const rotate = useMut(() => api(`/gates/${gate.id}/rotate-qr`, { method: "POST" }), [keys.sites]);
  const toggle = useMut(
    () => (gate.is_active
      ? api(`/gates/${gate.id}`, { method: "DELETE" })
      : api(`/gates/${gate.id}`, { method: "PATCH", body: { is_active: true } })),
    [keys.sites],
  );
  async function copy() {
    await navigator.clipboard?.writeText(gate.checkin_url);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }
  return (
    <tr>
      <td className={`${td} font-medium`}>{gate.name}</td>
      <td className={td}>
        <div className="flex items-center gap-2">
          <code className="truncate rounded bg-paper px-1.5 py-0.5 font-mono text-xs text-ink-2" title={gate.checkin_url}>
            …/v/{gate.qr_token}
          </code>
          <button onClick={() => void copy()} className="text-xs font-medium text-brand hover:underline">
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </td>
      <td className={td}>{gate.is_active ? <Badge tone="ok">Active</Badge> : <Badge>Inactive</Badge>}</td>
      <td className={`${td} text-right whitespace-nowrap`}>
        {gate.is_active && <PosterButton path={`/gates/${gate.id}/poster.pdf`} label="Poster" />}
        <Button size="sm" variant="ghost" busy={rotate.isPending} title="Old posters for this gate stop working"
          onClick={() => confirm(`Generate a new QR for ${gate.name}? Printed posters for this gate will stop working.`) && rotate.mutate(undefined)}>
          New QR
        </Button>
        <Button size="sm" variant="ghost" busy={toggle.isPending} onClick={() => toggle.mutate(undefined)}>
          {gate.is_active ? "Disable" : "Enable"}
        </Button>
      </td>
    </tr>
  );
}

/** Downloads a branded A4 QR poster PDF (it also ticks "print posters" in the setup checklist). */
export function PosterButton({ path, label, variant = "ghost" }: { path: string; label: string; variant?: "ghost" | "secondary" | "primary" }) {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <Button size="sm" variant={variant} busy={busy} title={error ?? "A4 PDF with the QR code, your logo and colours"}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            await downloadFile(path, { fallbackName: "qr-poster.pdf" });
            void qc.invalidateQueries({ queryKey: ["onboarding"] });
          } catch (e) {
            setError(errorMessage(e));
            alert(errorMessage(e));
          } finally {
            setBusy(false);
          }
        }}>
        {label}
      </Button>
    </>
  );
}

function SiteDialog({ site, onClose }: { site: Site | "new" | null; onClose: () => void }) {
  const isNew = site === "new";
  // Send only editable fields; the API rejects unknown keys.
  const initial: SiteForm =
    site && site !== "new"
      ? (({ name, address, city, state, pincode, map_url, directions_text, safety_contacts }) => ({
          name, address, city, state, pincode, map_url, directions_text, safety_contacts,
        }))(site)
      : {};
  return (
    <Dialog open={site !== null} onClose={onClose} title={isNew ? "Add site" : "Edit site"}>
      {site !== null && <SiteFormBody key={isNew ? "new" : site.id} id={isNew ? null : site.id} initial={initial} onDone={onClose} />}
    </Dialog>
  );
}

function SiteFormBody({ id, initial, onDone }: { id: string | null; initial: SiteForm; onDone: () => void }) {
  const [f, setF] = useState<SiteForm>(initial);
  const [error, setError] = useState<string | null>(null);
  const save = useMut(
    (body: SiteForm) => (id ? api(`/sites/${id}`, { method: "PATCH", body }) : api("/sites", { method: "POST", body })),
    [keys.sites],
  );
  const set = (k: keyof SiteForm) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value || null });

  function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    save.mutate(f, { onSuccess: onDone, onError: (err) => setError(errorMessage(err)) });
  }
  return (
    <form onSubmit={submit} className="space-y-4">
      {error && <Alert>{error}</Alert>}
      <Field label="Site name">{(i) => <Input id={i} required value={f.name ?? ""} onChange={set("name")} placeholder="e.g. Bhubaneswar HQ" />}</Field>
      <Field label="Address">{(i) => <Input id={i} value={f.address ?? ""} onChange={set("address")} />}</Field>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Field label="City">{(i) => <Input id={i} value={f.city ?? ""} onChange={set("city")} />}</Field>
        <Field label="State">{(i) => <Input id={i} value={f.state ?? ""} onChange={set("state")} />}</Field>
        <Field label="PIN code">{(i) => <Input id={i} inputMode="numeric" pattern="\d{6}" value={f.pincode ?? ""} onChange={set("pincode")} />}</Field>
      </div>
      <Field label="Map link" hint="Sent to invited guests with their pass.">
        {(i) => <Input id={i} type="url" value={f.map_url ?? ""} onChange={set("map_url")} placeholder="https://maps.google.com/…" />}
      </Field>
      <Field label="Directions for visitors">{(i) => <Input id={i} value={f.directions_text ?? ""} onChange={set("directions_text")} placeholder="Enter from Gate 2, reception on ground floor" />}</Field>
      <SafetyContacts value={f.safety_contacts ?? []} onChange={(safety_contacts) => setF({ ...f, safety_contacts })} />
      {!id && <p className="text-xs text-ink-3">A "Main Gate" with its own QR code is created automatically.</p>}
      <div className="flex justify-end gap-2 pt-2">
        <Button type="button" variant="secondary" onClick={onDone}>Cancel</Button>
        <Button type="submit" busy={save.isPending}>{id ? "Save" : "Add site"}</Button>
      </div>
    </form>
  );
}

/** Who gets the evacuation list on WhatsApp when a guard or admin taps "Send". */
function SafetyContacts({ value, onChange }: { value: { name: string; phone: string }[]; onChange: (v: { name: string; phone: string }[]) => void }) {
  const put = (i: number, k: "name" | "phone", v: string) => onChange(value.map((c, j) => (j === i ? { ...c, [k]: v } : c)));
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm font-medium">Safety contacts</legend>
      <p className="text-xs text-ink-3">Fire wardens or security heads. In an emergency they get the list of visitors on site on WhatsApp.</p>
      {value.map((c, i) => (
        <div key={i} className="grid grid-cols-[1fr_1fr_auto] gap-2">
          <Input aria-label="Contact name" placeholder="Name" required value={c.name} onChange={(e) => put(i, "name", e.target.value)} />
          <Input aria-label="Contact mobile" placeholder="Mobile" type="tel" required value={c.phone} onChange={(e) => put(i, "phone", e.target.value)} />
          <Button type="button" variant="ghost" aria-label="Remove contact" onClick={() => onChange(value.filter((_, j) => j !== i))}>✕</Button>
        </div>
      ))}
      {value.length < 10 && <Button type="button" size="sm" variant="secondary" onClick={() => onChange([...value, { name: "", phone: "" }])}>+ Add contact</Button>}
    </fieldset>
  );
}

function GateDialog({ site, onClose }: { site: Site | null; onClose: () => void }) {
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const add = useMut((n: string) => api(`/sites/${site!.id}/gates`, { method: "POST", body: { name: n } }), [keys.sites]);
  return (
    <Dialog open={site !== null} onClose={onClose} title={`Add gate to ${site?.name ?? ""}`}>
      <form
        className="space-y-4"
        onSubmit={(e) => {
          e.preventDefault();
          add.mutate(name, { onSuccess: () => { setName(""); onClose(); }, onError: (err) => setError(errorMessage(err)) });
        }}
      >
        {error && <Alert>{error}</Alert>}
        <Field label="Gate name">{(i) => <Input id={i} required autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Tower B Lobby" />}</Field>
        <div className="flex justify-end gap-2">
          <Button type="button" variant="secondary" onClick={onClose}>Cancel</Button>
          <Button type="submit" busy={add.isPending}>Add gate</Button>
        </div>
      </form>
    </Dialog>
  );
}
