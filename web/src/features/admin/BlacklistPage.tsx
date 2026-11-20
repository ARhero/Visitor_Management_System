import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Alert, Badge, Button, Card, Dialog, Empty, Field, Input, PageHeader, Select, Spinner, cx, td, th } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatIST, formatPhone } from "@/lib/time";
import type { Page } from "@/lib/types";
import { useMut, useSites } from "./queries";

interface Entry {
  id: string;
  phone: string;
  name: string | null;
  reason: string;
  action: "block" | "alert";
  site_id: string | null;
  site_name: string | null;
  expires_at: string | null;
  is_active: boolean;
  added_by_name: string | null;
  created_at: string;
  hits: number;
}

const KEY = ["blacklist"] as const;

function EntryDialog({ open, onClose, entry }: { open: boolean; onClose: () => void; entry?: Entry | null }) {
  const sites = useSites();
  const [v, setV] = useState({
    phone: entry?.phone ?? "",
    name: entry?.name ?? "",
    reason: entry?.reason ?? "",
    action: entry?.action ?? "block",
    site_id: entry?.site_id ?? "",
    expires: entry?.expires_at ? entry.expires_at.slice(0, 10) : "",
  });
  const set = (k: keyof typeof v) => (e: { target: { value: string } }) => setV({ ...v, [k]: e.target.value });
  const m = useMut(
    () => {
      const body = {
        name: v.name || null,
        reason: v.reason,
        action: v.action,
        site_id: v.site_id || null,
        // End of the chosen day, IST.
        expires_at: v.expires ? `${v.expires}T23:59:59+05:30` : null,
      };
      return entry
        ? api(`/blacklist/${entry.id}`, { method: "PATCH", body })
        : api("/blacklist", { method: "POST", body: { ...body, phone: v.phone } });
    },
    [KEY],
  );
  const submit = (e: FormEvent) => {
    e.preventDefault();
    m.mutate(undefined, { onSuccess: onClose });
  };
  return (
    <Dialog open={open} onClose={onClose} title={entry ? "Edit entry" : "Add to blacklist"}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="bl-form" busy={m.isPending}>{entry ? "Save" : "Add"}</Button></>}>
      <form id="bl-form" onSubmit={submit} className="space-y-4">
        <Field label="Mobile number" hint="Matched on check-in, walk-in and when an invite pass is scanned.">
          {(id) => <Input id={id} type="tel" required disabled={!!entry} value={v.phone} onChange={set("phone")} />}
        </Field>
        <Field label="Name (optional)">{(id) => <Input id={id} value={v.name} onChange={set("name")} maxLength={200} />}</Field>
        <Field label="Reason" hint="Shown to the guard at the gate, never to the visitor.">
          {(id) => <Input id={id} required minLength={3} maxLength={500} value={v.reason} onChange={set("reason")} />}
        </Field>
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium">What happens</legend>
          {([["block", "Block", "Check-in is refused; the visitor is asked to see security. The host isn't asked."],
            ["alert", "Alert", "The visit goes ahead as normal, flagged for the guard with your reason."]] as const).map(([k, label, help]) => (
            <label key={k} className={cx("flex cursor-pointer gap-3 rounded-lg border p-3", v.action === k ? "border-brand bg-brand-50" : "border-line")}>
              <input type="radio" name="action" checked={v.action === k} onChange={() => setV({ ...v, action: k })} className="mt-1 accent-brand" />
              <span><span className="block text-sm font-medium">{label}</span><span className="block text-xs text-ink-3">{help}</span></span>
            </label>
          ))}
        </fieldset>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Site">
            {(id) => (
              <Select id={id} value={v.site_id} onChange={set("site_id")}>
                <option value="">All sites</option>
                {sites.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
              </Select>
            )}
          </Field>
          <Field label="Until (optional)">{(id) => <Input id={id} type="date" value={v.expires} onChange={set("expires")} />}</Field>
        </div>
        {m.error && <Alert>{errorMessage(m.error)}</Alert>}
      </form>
    </Dialog>
  );
}

export default function BlacklistPage() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(true);
  const [editing, setEditing] = useState<Entry | null | undefined>(undefined);
  const list = useQuery({
    queryKey: [...KEY, q, active],
    queryFn: () => api<Page<Entry>>("/blacklist", { query: { q, active, limit: 200 } }),
    placeholderData: (p) => p,
  });
  const remove = useMut((id: string) => api(`/blacklist/${id}`, { method: "DELETE" }), [KEY]);

  return (
    <>
      <PageHeader
        title="Blacklist"
        description="People who must not be let in, or whose arrival the guard should be warned about. Matched by mobile number."
        actions={<Button onClick={() => setEditing(null)}>Add person</Button>}
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Input className="max-w-xs" type="search" placeholder="Search name or number" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="flex items-center gap-2 text-sm text-ink-2">
          <input type="checkbox" checked={!active} onChange={(e) => setActive(!e.target.checked)} className="accent-brand" /> Show removed
        </label>
      </div>
      <Card padded={false}>
        {list.isLoading ? <Spinner /> : !list.data?.items.length ? (
          <Empty title="Nobody on the list">Add someone to stop them at the gate or get an alert when they arrive.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead className="border-b border-line"><tr>
                <th className={th}>Person</th><th className={th}>Action</th><th className={th}>Reason</th><th className={th}>Where</th><th className={th}>Attempts</th><th className={th} />
              </tr></thead>
              <tbody className="divide-y divide-line">
                {list.data.items.map((e) => (
                  <tr key={e.id} className={e.is_active ? "" : "opacity-60"}>
                    <td className={td}><p className="font-medium">{e.name || "—"}</p><p className="text-xs text-ink-3">{formatPhone(e.phone)}</p></td>
                    <td className={td}><Badge tone={e.action === "block" ? "bad" : "warn"}>{e.action === "block" ? "Block" : "Alert"}</Badge></td>
                    <td className={cx(td, "max-w-xs")}><p className="truncate">{e.reason}</p><p className="text-xs text-ink-3">Added {formatIST(e.created_at)}{e.added_by_name && ` by ${e.added_by_name}`}</p></td>
                    <td className={td}>{e.site_name ?? "All sites"}{e.expires_at && <p className="text-xs text-ink-3">until {formatIST(e.expires_at)}</p>}</td>
                    <td className={td}>{e.hits}</td>
                    <td className={cx(td, "whitespace-nowrap text-right")}>
                      {e.is_active && (
                        <>
                          <Button size="sm" variant="ghost" onClick={() => setEditing(e)}>Edit</Button>
                          <Button size="sm" variant="ghost" onClick={() => window.confirm(`Remove ${e.name || formatPhone(e.phone)} from the blacklist?`) && remove.mutate(e.id)}>Remove</Button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {remove.error && <div className="mt-3"><Alert>{errorMessage(remove.error)}</Alert></div>}
      {editing !== undefined && (
        <EntryDialog key={editing?.id ?? "new"} open onClose={() => { setEditing(undefined); void qc.invalidateQueries({ queryKey: KEY }); }} entry={editing} />
      )}
    </>
  );
}
