import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Alert, Badge, Button, Dialog, td, th } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { formatPhone } from "@/lib/time";
import type { ImportResult } from "@/lib/types";

async function upload(file: File, dryRun: boolean) {
  const fd = new FormData();
  fd.append("file", file);
  return api<ImportResult>("/users/import", { method: "POST", body: fd, query: { dry_run: dryRun } });
}

/** Two-step import: preview (dry run) → confirm. A file with any error is never committed. */
export function ImportDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [done, setDone] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function close() {
    setFile(null);
    setPreview(null);
    setDone(null);
    setError(null);
    onClose();
  }

  async function run(f: File, dryRun: boolean) {
    setBusy(true);
    setError(null);
    try {
      const r = await upload(f, dryRun);
      if (dryRun) setPreview(r);
      else {
        setDone(r);
        await qc.invalidateQueries({ queryKey: ["users"] });
        await qc.invalidateQueries({ queryKey: ["departments"] });
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  const footer = done ? (
    <Button onClick={close}>Done</Button>
  ) : preview ? (
    <>
      <Button variant="secondary" onClick={() => { setPreview(null); setFile(null); }}>Choose another file</Button>
      <Button disabled={preview.errors > 0 || preview.created + preview.updated === 0} busy={busy} onClick={() => file && run(file, false)}>
        Import {preview.created + preview.updated} {preview.created + preview.updated === 1 ? "person" : "people"}
      </Button>
    </>
  ) : null;

  return (
    <Dialog open={open} onClose={close} title="Import hosts from CSV" wide footer={footer}>
      {error && <div className="mb-4"><Alert>{error}</Alert></div>}
      {done ? (
        <Alert tone="ok">
          Imported: {done.created} added, {done.updated} updated
          {done.new_departments.length > 0 && `. New departments: ${done.new_departments.join(", ")}`}.
        </Alert>
      ) : !preview ? (
        <div className="space-y-4">
          <p className="text-sm text-ink-2">
            Required columns: <code className="font-mono text-xs">full_name</code>, <code className="font-mono text-xs">phone</code>. Optional:{" "}
            <code className="font-mono text-xs">email, department, designation, employee_code, site, backup_host_phone</code>.
            People already in VMS are matched by phone or email and updated.
          </p>
          <a href="/api/v1/users/import/template.csv" className="text-sm font-medium text-brand hover:underline"
            onClick={async (e) => {
              // Authenticated download
              e.preventDefault();
              const text = await api<string>("/users/import/template.csv");
              const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
              Object.assign(document.createElement("a"), { href: url, download: "hosts-template.csv" }).click();
              URL.revokeObjectURL(url);
            }}>
            Download template
          </a>
          <label className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-line-strong px-6 py-10 text-center hover:border-brand hover:bg-brand-50/40">
            <span className="text-sm font-medium">{busy ? "Checking file…" : "Choose a CSV file"}</span>
            <span className="text-xs text-ink-3">Up to 5,000 rows · nothing is saved until you confirm</span>
            <input type="file" accept=".csv,text/csv" className="sr-only" disabled={busy}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) { setFile(f); void run(f, true); } }} />
          </label>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2 text-sm">
            <Badge tone="ok">{preview.created} new</Badge>
            <Badge tone="brand">{preview.updated} updates</Badge>
            {preview.errors > 0 && <Badge tone="bad">{preview.errors} with errors</Badge>}
            {preview.new_departments.length > 0 && <Badge>New departments: {preview.new_departments.join(", ")}</Badge>}
          </div>
          {preview.errors > 0 && <Alert tone="warn">Fix the highlighted rows in your file and upload it again. Nothing has been imported.</Alert>}
          <div className="max-h-80 overflow-auto rounded-lg border border-line">
            <table className="w-full">
              <thead className="sticky top-0 bg-surface">
                <tr className="border-b border-line"><th className={th}>Row</th><th className={th}>Name</th><th className={th}>Mobile</th><th className={th}>Result</th></tr>
              </thead>
              <tbody className="divide-y divide-line">
                {[...preview.rows].filter((r) => r.action !== "skip").sort((a, b) => Number(b.action === "error") - Number(a.action === "error")).map((r) => (
                  <tr key={r.row} className={r.action === "error" ? "bg-bad-50/50" : ""}>
                    <td className={`${td} text-ink-3`}>{r.row}</td>
                    <td className={td}>{r.full_name || "—"}</td>
                    <td className={`${td} whitespace-nowrap`}>{formatPhone(r.phone)}</td>
                    <td className={td}>
                      {r.action === "error" ? <span className="text-bad">{r.errors.join("; ")}</span>
                        : r.action === "update" ? <Badge tone="brand">Update</Badge> : <Badge tone="ok">New</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Dialog>
  );
}
