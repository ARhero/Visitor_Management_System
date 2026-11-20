import { useParams } from "react-router";
import { Spinner } from "@/components/ui";
import { Panel, PublicShell } from "./PublicShell";
import { errorText } from "./i18n";
import { pub } from "./publicApi";
import { useLoad } from "./useLoad";

interface Row {
  visit_id: string; visitor_name: string | null; visitor_company: string | null; visitor_phone: string | null;
  photo_url: string | null; host_name: string; host_phone: string | null; site_name: string; gate_name: string | null;
  accompanying_count: number; checked_in_at: string | null;
}
interface Shared { org_name: string; at: string; site_name: string | null; visits: number; people: number; rows: Row[] }

const clock = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true });
const tel = (p: string | null) => p && <a className="font-medium text-brand underline" href={`tel:${p}`}>{p.replace(/^\+91(\d{5})(\d{5})$/, "+91 $1 $2")}</a>;

/**
 * The link in an evacuation message shared on WhatsApp: everyone on site right now, as a
 * page (phone browsers opened from WhatsApp often can't show a PDF). Numbers are tap to
 * call; the page refreshes itself; the PDF is one tap away. Valid for a few hours.
 */
export default function EvacuationLinkPage() {
  const { token = "" } = useParams();
  const q = useLoad(`evac:${token}`, () => pub<Shared>(`/evacuation/${token}/data`), { refetchInterval: 30_000 });
  if (q.isLoading) return <PublicShell><Spinner /></PublicShell>;
  if (q.error || !q.data) return <PublicShell><Panel><p>{errorText(q.error)}</p></Panel></PublicShell>;
  const ev = q.data;
  return (
    <PublicShell org={ev.org_name} sub={ev.site_name ?? undefined}>
      <div className="space-y-4">
        <Panel>
          <p className="text-sm font-semibold uppercase tracking-wide text-bad">Evacuation list</p>
          <p className="mt-1 text-2xl font-semibold" data-testid="evac-count">{ev.people} people on site</p>
          <p className="text-sm text-ink-2">
            {ev.visits} visitor{ev.visits === 1 ? "" : "s"} checked in, plus people with them · as of {clock.format(new Date(ev.at))}, updates by itself
          </p>
          <a className="mt-4 flex h-12 items-center justify-center rounded-xl border border-brand text-base font-medium text-brand"
            href={`/api/v1/public/evacuation/${token}`} target="_blank" rel="noreferrer">Open as PDF</a>
        </Panel>
        {ev.rows.length === 0 ? (
          <Panel><p className="text-ink-2">Nobody is checked in right now.</p></Panel>
        ) : (
          <ul className="space-y-2">
            {ev.rows.map((r) => (
              <li key={r.visit_id} className="flex gap-3 rounded-xl border border-line bg-surface p-3">
                {r.photo_url ? <img src={r.photo_url} alt="" className="size-14 shrink-0 rounded-lg object-cover" />
                  : <div className="size-14 shrink-0 rounded-lg bg-paper" />}
                <div className="min-w-0 text-sm">
                  <p className="text-base font-semibold">
                    {r.visitor_name}{r.accompanying_count > 0 && <span className="font-normal text-ink-2"> +{r.accompanying_count}</span>}
                  </p>
                  {r.visitor_company && <p className="text-ink-3">{r.visitor_company}</p>}
                  {r.visitor_phone && <p>{tel(r.visitor_phone)}</p>}
                  <p className="mt-1 text-ink-2">Visiting {r.host_name}{r.host_phone && <> · {tel(r.host_phone)}</>}</p>
                  <p className="text-xs text-ink-3">
                    In since {r.checked_in_at ? clock.format(new Date(r.checked_in_at)) : "?"}{r.gate_name && ` · ${r.gate_name}`}
                  </p>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </PublicShell>
  );
}
