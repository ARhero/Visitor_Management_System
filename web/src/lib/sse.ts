/**
 * Server-sent events over fetch (so an Authorization header can be sent, which
 * EventSource can't do). Reconnects with backoff; the caller should also poll
 * occasionally as a safety net on flaky mobile networks.
 */
export function subscribe(
  url: string,
  token: string | (() => string | null),
  onEvent: (event: string, data: string) => void,
): () => void {
  const ctrl = new AbortController();
  let delay = 1000;

  async function run() {
    while (!ctrl.signal.aborted) {
      try {
        const tok = typeof token === "function" ? token() : token;
        const res = await fetch(url, { headers: { Authorization: `Bearer ${tok}`, Accept: "text/event-stream" }, signal: ctrl.signal });
        // Fixed token no longer valid: stop. A token getter may have a fresh one next time.
        if (res.status === 404 || (res.status === 401 && typeof token === "string")) return;
        if (!res.ok || !res.body) throw new Error(String(res.status));
        delay = 1000;
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        let buf = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buf += value;
          let i: number;
          while ((i = buf.indexOf("\n\n")) >= 0) {
            const block = buf.slice(0, i);
            buf = buf.slice(i + 2);
            let event = "message";
            const data: string[] = [];
            for (const line of block.split("\n")) {
              if (line.startsWith("event: ")) event = line.slice(7);
              else if (line.startsWith("data: ")) data.push(line.slice(6));
            }
            if (data.length) onEvent(event, data.join("\n"));
          }
        }
      } catch {
        if (ctrl.signal.aborted) return;
      }
      await new Promise((r) => setTimeout(r, delay));
      delay = Math.min(delay * 2, 15000);
    }
  }
  void run();
  return () => ctrl.abort();
}
