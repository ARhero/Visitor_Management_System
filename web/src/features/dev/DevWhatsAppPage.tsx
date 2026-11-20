import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { cx } from "@/components/ui";
import { formatPhone } from "@/lib/time";

interface Msg {
  id: string; org_name: string; direction: "out" | "in"; phone: string; template: string; text: string;
  buttons: { id: string; title: string }[]; status: string; error: string | null; created_at: string; visit_id: string | null;
}

const time = new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", hour: "numeric", minute: "2-digit", second: "2-digit", hour12: true });

async function get<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(r.status === 404 ? "The mock inbox only exists when the API runs with ENV=dev." : `HTTP ${r.status}`);
  return r.json();
}

/** Mock WhatsApp: every message the app "sent", per phone. Tapping a button goes
 *  through the same webhook processing as a real WhatsApp reply. */
export default function DevWhatsAppPage() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["dev-wa"], queryFn: () => get<Msg[]>("/api/v1/dev/whatsapp/messages?limit=300"), refetchInterval: 2000 });
  const [phone, setPhone] = useState<string | null>(null);
  const [last, setLast] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const threads = useMemo(() => {
    const m = new Map<string, Msg[]>();
    for (const x of q.data ?? []) m.set(x.phone, [...(m.get(x.phone) ?? []), x]);
    return [...m.entries()].map(([p, msgs]) => ({ phone: p, msgs: msgs.reverse(), latest: msgs[msgs.length - 1] }));
  }, [q.data]);
  const active = threads.find((t) => t.phone === phone) ?? threads[0];

  async function tap(m: Msg, b: { id: string; title: string }) {
    const r = await get<{ results: string[] }>(`/api/v1/dev/whatsapp/messages/${m.id}/reply`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ button_id: b.id }),
    });
    setLast(`${b.title} → ${r.results.join(", ")}`);
    void qc.invalidateQueries({ queryKey: ["dev-wa"] });
  }

  /** Type a message to the business number, as this person (e.g. STOP / START). */
  async function say(text: string) {
    if (!active || !text.trim()) return;
    const r = await get<{ results: string[] }>("/api/v1/dev/whatsapp/inbound", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ phone: active.phone, text }),
    });
    setLast(`"${text}" → ${r.results.join(", ")}`);
    setDraft("");
    void qc.invalidateQueries({ queryKey: ["dev-wa"] });
  }

  return (
    <div className="flex h-dvh flex-col bg-[#ece5dd] text-[15px]">
      <header className="flex items-center justify-between bg-[#075e54] px-4 py-3 text-white">
        <div>
          <p className="font-semibold">Mock WhatsApp</p>
          <p className="text-xs opacity-80">Dev only. Nothing here is really sent. Tap a button to simulate the reply.</p>
        </div>
        {last && <p className="hidden max-w-sm truncate rounded bg-white/15 px-2 py-1 text-xs sm:block" data-testid="last-tap">{last}</p>}
      </header>
      {q.error ? (
        <p className="m-4 rounded bg-white p-4">{(q.error as Error).message}</p>
      ) : (
        <div className="flex min-h-0 flex-1">
          <aside className="w-72 shrink-0 overflow-y-auto border-r border-black/10 bg-white max-sm:hidden">
            {threads.length === 0 && <p className="p-4 text-sm text-ink-3">No messages yet. Start a check-in at a gate link.</p>}
            {threads.map((t) => (
              <button key={t.phone} onClick={() => setPhone(t.phone)}
                className={cx("block w-full border-b border-black/5 px-4 py-3 text-left", active?.phone === t.phone && "bg-[#f0f2f5]")}>
                <p className="font-medium">{formatPhone(t.phone)}</p>
                <p className="truncate text-sm text-ink-3">{t.latest.text.split("\n")[0]}</p>
              </button>
            ))}
          </aside>
          <main className="flex min-w-0 flex-1 flex-col">
            <select className="m-2 rounded border bg-white p-2 sm:hidden" value={active?.phone ?? ""} onChange={(e) => setPhone(e.target.value)}>
              {threads.map((t) => <option key={t.phone} value={t.phone}>{formatPhone(t.phone)}</option>)}
            </select>
            <div className="flex-1 space-y-2 overflow-y-auto p-4" data-testid="thread">
              {active?.msgs.map((m) => (
                <div key={m.id} className={cx("max-w-[85%] rounded-lg px-3 py-2 shadow-sm sm:max-w-md", m.direction === "in" ? "ml-auto bg-[#dcf8c6]" : "bg-white")}
                  data-template={m.template}>
                  <p className="text-[11px] text-ink-3">{m.org_name} · {m.template}</p>
                  <p className="whitespace-pre-line break-words">{m.text}</p>
                  <p className={cx("mt-1 text-right text-[11px]", m.status === "skipped" || m.status === "failed" ? "text-bad" : "text-ink-3")}>
                    {time.format(new Date(m.created_at))} · {m.status}{m.error ? ` (${m.error})` : ""}
                  </p>
                  {m.buttons.length > 0 && (
                    <div className="-mx-3 -mb-2 mt-2 grid border-t border-black/10">
                      {m.buttons.map((b) => (
                        <button key={b.id} onClick={() => void tap(m, b)} className="border-b border-black/5 py-2 text-center font-medium text-[#00a5f4] last:border-0 hover:bg-black/5">
                          {b.title}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
            {active && (
              <form className="flex gap-2 border-t border-black/10 bg-[#f0f2f5] p-2" onSubmit={(e) => { e.preventDefault(); void say(draft); }}>
                <input className="min-w-0 flex-1 rounded-full bg-white px-4 py-2 outline-none" placeholder={`Message as ${formatPhone(active.phone)} (try STOP or START)`}
                  value={draft} onChange={(e) => setDraft(e.target.value)} aria-label="Message" />
                <button className="rounded-full bg-[#075e54] px-4 font-medium text-white disabled:opacity-50" disabled={!draft.trim()}>Send</button>
              </form>
            )}
          </main>
        </div>
      )}
    </div>
  );
}
