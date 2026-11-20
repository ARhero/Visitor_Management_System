import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { Alert, Button, Card, Empty, PageHeader, Select, Spinner, td, th } from "@/components/ui";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { openEvacuationPdf } from "@/lib/openPdf";
import { whatsappShareUrl } from "@/lib/share";
import { formatPhone } from "@/lib/time";
import { useOrgLive, type Evacuation } from "./insightsApi";
import { useSites } from "./queries";

const time = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", hour12: true });

/** Download / share actions, also used in the guard console. */
export function useEvacuationActions(siteId: string) {
  const [busy, setBusy] = useState<"pdf" | "share" | null>(null);
  // ``share``: WhatsApp is off, so the message comes back to be sent by hand.
  const [msg, setMsg] = useState<{ ok: boolean; text: string; share?: string } | null>(null);
  return {
    busy,
    msg,
    pdf: async () => {
      setBusy("pdf");
      setMsg(null);
      try {
        await openEvacuationPdf(siteId);
      } catch (e) {
        setMsg({ ok: false, text: errorMessage(e) });
      } finally {
        setBusy(null);
      }
    },
    share: async (confirmText: string | null, done: (r: { sent: number; people: number; share_text?: string }) => string) => {
      if (confirmText && !window.confirm(confirmText)) return;
      setBusy("share");
      setMsg(null);
      try {
        const r = await api<{ sent: number; people: number; share_text?: string }>("/evacuation/share", { method: "POST", body: { site_id: siteId } });
        setMsg({ ok: true, text: done(r), share: r.share_text });
      } catch (e) {
        setMsg({ ok: false, text: errorMessage(e) });
      } finally {
        setBusy(null);
      }
    },
  };
}

export default function EvacuationPage() {
  const [params, setParams] = useSearchParams();
  const siteId = params.get("site") ?? "";
  const sites = useSites();
  const q = useQuery({
    queryKey: ["evacuation", siteId],
    queryFn: () => api<Evacuation>("/evacuation", { query: { site_id: siteId || undefined } }),
    refetchInterval: 15_000,
  });
  useOrgLive([["evacuation"]]);
  const act = useEvacuationActions(siteId);
  const whatsapp = useAuth().me?.whatsapp_enabled !== false;
  const ev = q.data;
  const site = sites.data?.find((s) => s.id === siteId);

  return (
    <>
      <PageHeader
        title="Evacuation list"
        description="Everyone checked in right now, with phone numbers for a roll call at the assembly point. Updates live."
        actions={
          <>
            <Select aria-label="Site" className="w-52!" value={siteId} onChange={(e) => setParams(e.target.value ? { site: e.target.value } : {}, { replace: true })}>
              <option value="">All sites</option>
              {sites.data?.filter((s) => s.is_active).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </Select>
            <Button variant="secondary" busy={act.busy === "pdf"} onClick={() => void act.pdf()}>Download PDF</Button>
            <Button variant="danger" disabled={!siteId} title={siteId ? undefined : "Choose a site"} busy={act.busy === "share"}
              onClick={() => void act.share(
                whatsapp ? `Send the evacuation list for ${site?.name} to its safety contacts on WhatsApp now?` : null,
                (r) => r.share_text ? `${r.people} people on site. Send the message with the live list from your WhatsApp:` : `Sent to ${r.sent} safety contact(s): ${r.people} people on site.`)}>
              {whatsapp ? "Send to safety contacts" : "Share on WhatsApp"}
            </Button>
          </>
        }
      />
      {act.msg && (
        <div className="mb-4">
          <Alert tone={act.msg.ok ? "ok" : "bad"}>
            {act.msg.text}
            {act.msg.share && <> <a className="font-semibold underline" href={whatsappShareUrl(act.msg.share)} target="_blank" rel="noreferrer">Open WhatsApp</a></>}
          </Alert>
        </div>
      )}
      {q.error && <Alert>{errorMessage(q.error)}</Alert>}
      {!ev ? <Spinner /> : (
        <>
          <div className="mb-4 flex flex-wrap items-baseline gap-x-6 gap-y-1">
            <p className="text-3xl font-semibold tabular-nums" data-testid="evac-people">{ev.people} <span className="text-base font-normal text-ink-2">people on site</span></p>
            <p className="text-sm text-ink-2">{ev.visits} visitors checked in, plus people with them · as of {time.format(new Date(ev.at))}</p>
          </div>
          {siteId && (
            <p className="mb-4 text-sm text-ink-2">
              Safety contacts: {ev.contacts.length ? ev.contacts.map((c) => `${c.name} (${formatPhone(c.phone)})`).join(", ") : <>none yet. <Link to="/admin/sites" className="text-brand hover:underline">Add them in Sites &amp; gates</Link></>}
            </p>
          )}
          <Card padded={false}>
            {!ev.rows.length ? <Empty title="Nobody is checked in">The list fills as visitors check in.</Empty> : (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="border-b border-line"><tr>
                    <th className={th}>Visitor</th><th className={th}>Phone</th><th className={th}>With</th><th className={th}>Host</th><th className={th}>Where</th><th className={th}>In since</th>
                  </tr></thead>
                  <tbody className="divide-y divide-line">
                    {ev.rows.map((r) => (
                      <tr key={r.visit_id}>
                        <td className={td}>
                          <div className="flex items-center gap-3">
                            {r.photo_url ? <img src={r.photo_url} alt="" className="size-10 rounded-lg object-cover" /> : <div className="size-10 rounded-lg bg-paper" />}
                            <div><p className="font-medium">{r.visitor_name}</p><p className="text-xs text-ink-3">{r.visitor_company}</p></div>
                          </div>
                        </td>
                        <td className={`${td} whitespace-nowrap`}><a href={`tel:${r.visitor_phone}`} className="text-brand">{formatPhone(r.visitor_phone)}</a></td>
                        <td className={td}>{r.accompanying_count ? `+${r.accompanying_count}` : ""}</td>
                        <td className={td}>{r.host_name}<p className="whitespace-nowrap text-xs"><a href={`tel:${r.host_phone}`} className="text-brand">{formatPhone(r.host_phone)}</a></p></td>
                        <td className={td}>{r.site_name}<p className="text-xs text-ink-3">{r.gate_name}</p></td>
                        <td className={td}>{r.checked_in_at && time.format(new Date(r.checked_in_at))}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
