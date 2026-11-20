import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Card, Empty, Input, PageHeader, Spinner, td, th } from "@/components/ui";
import { api } from "@/lib/api";
import { formatIST } from "@/lib/time";
import type { AuditEntry, Page } from "@/lib/types";

const PAGE = 50;

const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v);

/** Readable summary of an audit diff. "*.update" entries hold {field: [old, new]}; nested
 *  objects (settings, branding) are expanded to the keys that changed
 *  ("settings.retention_days: 90 → 120"). Other entries hold plain values. */
export function summarize(action: string, diff: Record<string, unknown>, max = 4): string {
  const isChange = action.endsWith("update");
  const parts: string[] = [];
  for (const [k, v] of Object.entries(diff)) {
    if (!isChange || !Array.isArray(v) || v.length !== 2) {
      parts.push(`${k}: ${fmt(v)}`);
    } else if (isObj(v[0]) && isObj(v[1])) {
      const [a, b] = v as [Record<string, unknown>, Record<string, unknown>];
      for (const sub of new Set([...Object.keys(a), ...Object.keys(b)])) {
        if (JSON.stringify(a[sub]) !== JSON.stringify(b[sub])) parts.push(`${k}.${sub}: ${fmt(a[sub])} → ${fmt(b[sub])}`);
      }
    } else {
      parts.push(`${k}: ${fmt(v[0])} → ${fmt(v[1])}`);
    }
  }
  const more = parts.length - max;
  return parts.slice(0, max).join(" · ") + (more > 0 ? ` · +${more} more` : "");
}
function fmt(v: unknown): string {
  if (v === null || v === undefined || v === "") return "∅";
  if (Array.isArray(v)) return v.length === 0 ? "∅" : v.length <= 3 && v.every((x) => typeof x !== "object") ? v.join(", ") : `${v.length} items`;
  if (typeof v === "object") return "…";
  const s = String(v);
  return s.length > 28 ? `${s.slice(0, 26)}…` : s;
}

export default function AuditPage() {
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const { data, isLoading } = useQuery({
    queryKey: ["audit", action, offset],
    queryFn: () => api<Page<AuditEntry>>("/audit-logs", { query: { action: action || undefined, limit: PAGE, offset } }),
    placeholderData: (p) => p,
  });
  return (
    <>
      <PageHeader title="Audit log" description="Every change made by an admin, with who, when and from where. Entries cannot be edited or deleted." />
      <Card padded={false}>
        <div className="border-b border-line p-3">
          <Input className="max-w-xs" placeholder="Filter by action, e.g. user. or gate.rotate" value={action}
            onChange={(e) => { setAction(e.target.value); setOffset(0); }} aria-label="Filter by action" />
        </div>
        {isLoading ? <Spinner /> : !data?.items.length ? <Empty title="No entries" /> : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px]">
              <thead className="border-b border-line"><tr><th className={th}>When (IST)</th><th className={th}>Who</th><th className={th}>Action</th><th className={th}>Change</th><th className={th}>IP</th></tr></thead>
              <tbody className="divide-y divide-line">
                {data.items.map((a) => (
                  <tr key={a.id}>
                    <td className={`${td} whitespace-nowrap text-ink-2`}>{formatIST(a.created_at)}</td>
                    <td className={`${td} whitespace-nowrap`}>{a.actor_name ?? (a.actor_type === "system" ? "System" : "—")}</td>
                    <td className={td}><code className="font-mono text-xs">{a.action}</code></td>
                    <td className={`${td} text-ink-2`}>{summarize(a.action, a.diff) || "—"}</td>
                    <td className={`${td} font-mono text-xs text-ink-3`}>{a.ip ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {data && data.total > PAGE && (
          <div className="flex justify-end gap-2 border-t border-line px-4 py-2.5">
            <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>Newer</Button>
            <Button size="sm" variant="secondary" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>Older</Button>
          </div>
        )}
      </Card>
    </>
  );
}
