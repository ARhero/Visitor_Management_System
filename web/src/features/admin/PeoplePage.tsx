import { useMemo, useState, type FormEvent } from "react";
import { Alert, Badge, Button, Card, Checkbox, Dialog, Empty, Field, Input, PageHeader, Select, Spinner, td, th } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { openWhatsApp } from "@/lib/share";
import { formatIST, formatPhone } from "@/lib/time";
import type { Role, User } from "@/lib/types";
import { ImportDialog } from "./ImportDialog";
import { keys, useDepartments, useMut, useSites, useUsers } from "./queries";

const ROLE_LABEL: Record<Role, string> = { org_admin: "Admin", guard: "Guard", host: "Host" };
const PAGE = 50;

export default function PeoplePage() {
  const whatsapp = useAuth().me?.whatsapp_enabled !== false;
  const [q, setQ] = useState("");
  const [role, setRole] = useState("");
  const [dept, setDept] = useState("");
  const [inactive, setInactive] = useState(false);
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const [importing, setImporting] = useState(false);

  const query = { q: q.trim() || undefined, role: role || undefined, department_id: dept || undefined, include_inactive: inactive, limit: PAGE, offset };
  const { data, isLoading, isFetching } = useUsers(query);
  const { data: depts } = useDepartments();
  const { data: sites } = useSites();
  const deptName = useMemo(() => new Map(depts?.map((d) => [d.id, d.name])), [depts]);
  const siteName = useMemo(() => new Map(sites?.map((s) => [s.id, s.name])), [sites]);
  const reset = () => setOffset(0);

  return (
    <>
      <PageHeader
        title="People"
        description="Hosts receive visitor approvals on WhatsApp. Guards and admins sign in to the web app."
        actions={
          <>
            <Button variant="secondary" onClick={() => setImporting(true)}>Import CSV</Button>
            <Button onClick={() => setEditing("new")}>Add person</Button>
          </>
        }
      />
      <Card padded={false}>
        <div className="flex flex-wrap items-center gap-2 border-b border-line p-3">
          <Input className="max-w-xs" placeholder="Search name, email, phone, code" value={q} onChange={(e) => { setQ(e.target.value); reset(); }} aria-label="Search people" />
          <Select className="w-auto" value={role} onChange={(e) => { setRole(e.target.value); reset(); }} aria-label="Role">
            <option value="">All roles</option>
            <option value="host">Hosts</option>
            <option value="guard">Guards</option>
            <option value="org_admin">Admins</option>
          </Select>
          <Select className="w-auto" value={dept} onChange={(e) => { setDept(e.target.value); reset(); }} aria-label="Department">
            <option value="">All departments</option>
            {depts?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
          <label className="ml-auto flex items-center gap-2 text-sm text-ink-2">
            <input type="checkbox" className="accent-brand" checked={inactive} onChange={(e) => { setInactive(e.target.checked); reset(); }} />
            Include deactivated
          </label>
        </div>
        {isLoading ? (
          <Spinner />
        ) : !data?.items.length ? (
          <Empty title={q || role || dept ? "Nobody matches these filters" : "No people yet"}>
            {!(q || role || dept) && "Import your host list from a CSV, or add people one by one."}
          </Empty>
        ) : (
          <div className={`overflow-x-auto ${isFetching ? "opacity-70" : ""}`}>
            <table className="w-full min-w-[760px]">
              <thead className="border-b border-line">
                <tr>
                  <th className={th}>Name</th><th className={th}>Mobile</th><th className={th}>Department</th>
                  <th className={th}>Site</th><th className={th}>Roles</th><th className={th}>Last sign-in</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {data.items.map((u) => (
                  <tr key={u.id} onClick={() => setEditing(u)} className="cursor-pointer hover:bg-paper">
                    <td className={td}>
                      <p className={`font-medium ${u.is_active ? "" : "text-ink-3 line-through"}`}>{u.full_name}</p>
                      <p className="text-xs text-ink-3">{[u.designation, u.email].filter(Boolean).join(" · ")}</p>
                    </td>
                    <td className={`${td} whitespace-nowrap`}>{formatPhone(u.phone)}</td>
                    <td className={td}>{(u.department_id && deptName.get(u.department_id)) || "—"}</td>
                    <td className={td}>{(u.primary_site_id && siteName.get(u.primary_site_id)) || "—"}</td>
                    <td className={td}>
                      <div className="flex flex-wrap gap-1">
                        {u.roles.map((r) => <Badge key={r} tone={r === "org_admin" ? "brand" : "neutral"}>{ROLE_LABEL[r]}</Badge>)}
                      </div>
                    </td>
                    <td className={`${td} whitespace-nowrap text-ink-2`}>{u.has_password || u.last_login_at ? formatIST(u.last_login_at) : <span className="text-ink-3">{whatsapp ? "WhatsApp link" : "Sign-in link"}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > PAGE && (
          <div className="flex items-center justify-between border-t border-line px-4 py-2.5 text-sm text-ink-2">
            <span>{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>Previous</Button>
              <Button size="sm" variant="secondary" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Next</Button>
            </div>
          </div>
        )}
      </Card>
      <PersonDialog user={editing} onClose={() => setEditing(null)} />
      <ImportDialog open={importing} onClose={() => setImporting(false)} />
    </>
  );
}

interface PersonForm {
  full_name: string;
  email: string;
  phone: string;
  roles: Role[];
  department_id: string;
  designation: string;
  employee_code: string;
  primary_site_id: string;
  password: string;
  site_ids: string[];
}

function PersonDialog({ user, onClose }: { user: User | "new" | null; onClose: () => void }) {
  return (
    <Dialog open={user !== null} onClose={onClose} title={user === "new" ? "Add person" : "Edit person"} wide>
      {user !== null && <PersonFormBody key={user === "new" ? "new" : user.id} user={user === "new" ? null : user} onDone={onClose} />}
    </Dialog>
  );
}

function PersonFormBody({ user, onDone }: { user: User | null; onDone: () => void }) {
  const whatsapp = useAuth().me?.whatsapp_enabled !== false;
  const { data: depts } = useDepartments();
  const { data: sites } = useSites();
  const [f, setF] = useState<PersonForm>({
    full_name: user?.full_name ?? "",
    email: user?.email ?? "",
    phone: user?.phone ?? "",
    roles: user?.roles ?? ["host"],
    department_id: user?.department_id ?? "",
    designation: user?.designation ?? "",
    employee_code: user?.employee_code ?? "",
    primary_site_id: user?.primary_site_id ?? "",
    password: "",
    site_ids: user?.site_ids ?? [],
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const invalidate = useMut(async () => undefined, [["users"], keys.departments]);
  const deactivate = useMut(() => api(`/users/${user!.id}`, { method: "DELETE" }), [["users"]]);

  const needsPassword = f.roles.some((r) => r === "org_admin" || r === "guard") && !user?.has_password;
  const set = (k: keyof PersonForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });
  const toggleRole = (r: Role) => setF({ ...f, roles: f.roles.includes(r) ? f.roles.filter((x) => x !== r) : [...f.roles, r] });

  async function submit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    const body = {
      full_name: f.full_name,
      email: f.email || null,
      phone: f.phone || null,
      roles: f.roles,
      department_id: f.department_id || null,
      designation: f.designation || null,
      employee_code: f.employee_code || null,
      primary_site_id: f.primary_site_id || null,
      ...(f.password ? { password: f.password } : {}),
      ...(user && !user.is_active ? { is_active: true } : {}),
    };
    try {
      const saved = user
        ? await api<User>(`/users/${user.id}`, { method: "PATCH", body })
        : await api<User>("/users", { method: "POST", body });
      if (f.roles.includes("guard")) {
        await api(`/users/${saved.id}/sites`, { method: "PUT", body: { site_ids: f.site_ids } });
      }
      await invalidate.mutateAsync(undefined);
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      {error && <Alert>{error}</Alert>}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <Field label="Full name">{(i) => <Input id={i} required value={f.full_name} onChange={set("full_name")} />}</Field>
        <Field label="Mobile number" hint="Hosts get approval requests on this WhatsApp number.">
          {(i) => <Input id={i} type="tel" inputMode="tel" value={f.phone} onChange={set("phone")} placeholder="98765 43210" />}
        </Field>
        <Field label="Email">{(i) => <Input id={i} type="email" value={f.email} onChange={set("email")} />}</Field>
        <Field label="Employee code">{(i) => <Input id={i} value={f.employee_code} onChange={set("employee_code")} />}</Field>
        <Field label="Department">
          {(i) => (
            <Select id={i} value={f.department_id} onChange={set("department_id")}>
              <option value="">—</option>
              {depts?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          )}
        </Field>
        <Field label="Designation">{(i) => <Input id={i} value={f.designation} onChange={set("designation")} />}</Field>
        <Field label="Primary site">
          {(i) => (
            <Select id={i} value={f.primary_site_id} onChange={set("primary_site_id")}>
              <option value="">—</option>
              {sites?.filter((s) => s.is_active).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
          )}
        </Field>
      </div>

      <fieldset className="space-y-2">
        <legend className="mb-1 text-sm font-medium">Roles</legend>
        <Checkbox label="Host" hint={whatsapp ? "Can be visited; approves visitors on WhatsApp or in the host app" : "Can be visited; approves visitors in the host app (phone alerts)"} checked={f.roles.includes("host")} onChange={() => toggleRole("host")} />
        <Checkbox label="Guard / reception" hint="Signs in to the guard console at assigned sites" checked={f.roles.includes("guard")} onChange={() => toggleRole("guard")} />
        <Checkbox label="Admin" hint="Manages sites, people, settings and reports" checked={f.roles.includes("org_admin")} onChange={() => toggleRole("org_admin")} />
      </fieldset>

      {f.roles.includes("guard") && (
        <fieldset className="space-y-2">
          <legend className="mb-1 text-sm font-medium">Guard sites</legend>
          {sites?.filter((s) => s.is_active).map((s) => (
            <Checkbox key={s.id} label={s.name} checked={f.site_ids.includes(s.id)}
              onChange={() => setF({ ...f, site_ids: f.site_ids.includes(s.id) ? f.site_ids.filter((x) => x !== s.id) : [...f.site_ids, s.id] })} />
          ))}
        </fieldset>
      )}

      <Field
        label={user?.has_password ? "Reset password" : needsPassword ? "Initial password" : "Password (optional)"}
        hint={user?.has_password
          ? "Leave empty to keep the current one. Resetting signs them out everywhere."
          : needsPassword
            ? "At least 10 characters. Share it with them securely."
            : "Lets them sign in with their mobile number and this password, as well as with sign-in links. At least 10 characters. Anyone already signed in stays signed in."}>
        {(i) => <Input id={i} type="password" autoComplete="new-password" minLength={10} required={needsPassword} value={f.password} onChange={set("password")} />}
      </Field>

      {user?.is_active && <SignInLink user={user} />}

      <div className="flex items-center justify-between border-t border-line pt-4">
        {user?.is_active ? (
          <Button type="button" variant="danger" busy={deactivate.isPending}
            onClick={() => confirm(`Deactivate ${user.full_name}? They will be signed out and stop receiving visitors.`) &&
              deactivate.mutate(undefined, { onSuccess: onDone, onError: (err) => setError(errorMessage(err)) })}>
            Deactivate
          </Button>
        ) : <span />}
        <div className="flex gap-2">
          <Button type="button" variant="secondary" onClick={onDone}>Cancel</Button>
          <Button type="submit" busy={busy}>{user ? (user.is_active ? "Save" : "Save & reactivate") : "Add person"}</Button>
        </div>
      </div>
    </form>
  );
}


interface LinkOut { url: string; expires_at: string; phone: string | null; full_name: string }

/** A one-time sign-in link the admin sends themselves (e.g. from their own WhatsApp). */
function SignInLink({ user }: { user: User }) {
  const { me } = useAuth();
  const [link, setLink] = useState<LinkOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  async function create() {
    setBusy(true);
    setNote(null);
    try {
      setLink(await api<LinkOut>(`/users/${user.id}/sign-in-link`, { method: "POST" }));
    } catch (e) {
      setNote(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }
  const text = link
    ? `Sign in to ${me?.org?.name ?? "VMS"} visitor management: ${link.url}
The link works once and expires on ${formatIST(link.expires_at)}.`
    : "";
  return (
    <div className="rounded-lg border border-line bg-paper p-3 text-sm" data-testid="sign-in-link">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">Sign-in link</p>
          <p className="text-ink-3">A link that signs {user.full_name} in once, without a password. Valid for 3 days.</p>
        </div>
        {!link && <Button type="button" size="sm" variant="secondary" busy={busy} onClick={() => void create()}>Create link</Button>}
      </div>
      {link && (
        <div className="mt-2 space-y-2">
          <Input readOnly value={link.url} onFocus={(e) => e.target.select()} aria-label="Sign-in link" />
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" onClick={() => openWhatsApp(text, link.phone)}>Share on WhatsApp</Button>
            <Button type="button" size="sm" variant="secondary" onClick={() => void navigator.clipboard?.writeText(link.url).then(() => setNote("Copied"))}>Copy</Button>
          </div>
        </div>
      )}
      {note && <p className="mt-1 text-ink-2" role="status">{note}</p>}
    </div>
  );
}
