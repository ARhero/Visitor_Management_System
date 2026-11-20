import { beforeAll, describe, expect, it, vi } from "vitest";
import { checkOffline, tokenFrom, type OfflineEntry, type OfflinePack } from "./offlinePass";

/** Passes signed here with a fresh Ed25519 key, exactly as the API signs them. */

const enc = (o: unknown) => b64(new TextEncoder().encode(JSON.stringify(o)));
function b64(bytes: Uint8Array) {
  return btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
async function sha(s: string) {
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s)));
  return [...d].map((b) => b.toString(16).padStart(2, "0")).join("");
}

let keys: CryptoKeyPair;
let jwkX: string;
const NOW = new Date("2026-11-20T06:00:00Z"); // 11:30 IST

async function pass(jti: string, exp = NOW.getTime() / 1000 + 3600, key = keys.privateKey) {
  const signed = `${enc({ alg: "EdDSA", typ: "JWT" })}.${enc({ jti, exp })}`;
  const sig = new Uint8Array(await crypto.subtle.sign({ name: "Ed25519" }, key, new TextEncoder().encode(signed)));
  return `${signed}.${b64(sig)}`;
}

function entry(h: string, over: Partial<OfflineEntry> = {}): OfflineEntry {
  return {
    h, kind: "visit", ref_id: "v1", name: "Ravi Kumar", company: "Acme", host_name: "Meera", purpose: "Meeting",
    state: "approved", accompanying_count: 0, valid_from: null, valid_until: "2026-11-20T18:29:00Z",
    daily_start_time: null, daily_end_time: null, consented: true, photo_url: null, alert: null, ...over,
  };
}

async function packWith(...entries: OfflineEntry[]): Promise<OfflinePack> {
  return { site_id: "s", generated_at: NOW.toISOString(), use_until: "2026-11-20T18:30:00Z", key: { kty: "OKP", crv: "Ed25519", x: jwkX }, entries };
}

beforeAll(async () => {
  keys = (await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"])) as CryptoKeyPair;
  jwkX = (await crypto.subtle.exportKey("jwk", keys.publicKey)).x!;
});

describe("checking a pass on the device", () => {
  it("recognises an expected pass, also from a pass link", async () => {
    const tok = await pass("abc123");
    const p = await packWith(entry(await sha("abc123")));
    const r = await checkOffline(tok, p, NOW);
    expect(r.status).toBe("ok");
    expect(r.entry?.name).toBe("Ravi Kumar");
    expect((await checkOffline(`https://vms.example.in/p/${tok}`, p, NOW)).status).toBe("ok");
    expect(tokenFrom(`http://x/p/${tok}?utm=1`)).toBe(tok);
  });

  it("rejects forged, tampered and foreign-key passes", async () => {
    const p = await packWith(entry(await sha("abc123")));
    const tok = await pass("abc123");
    const [h, , s] = tok.split(".");
    expect((await checkOffline(`${h}.${enc({ jti: "abc123", exp: 9e9 })}.${s}`, p, NOW)).status).toBe("invalid");
    const other = (await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"])) as CryptoKeyPair;
    expect((await checkOffline(await pass("abc123", undefined, other.privateKey), p, NOW)).status).toBe("invalid");
    expect((await checkOffline("not-a-pass", p, NOW)).status).toBe("invalid");
  });

  it("still verifies on browsers without Ed25519 in WebCrypto (library fallback)", async () => {
    const p = await packWith(entry(await sha("abc123")));
    const spy = vi.spyOn(crypto.subtle, "importKey").mockRejectedValue(new Error("NotSupportedError"));
    try {
      expect((await checkOffline(await pass("abc123"), p, NOW)).status).toBe("ok");
      const tok = await pass("abc123");
      expect((await checkOffline(tok.slice(0, -3) + "AAA", p, NOW)).status).toBe("invalid");
    } finally {
      spy.mockRestore();
    }
  });

  it("knows expired, unknown, inside and blocked", async () => {
    const p = await packWith(
      entry(await sha("in"), { state: "checked_in" }),
      entry(await sha("bad"), { alert: { action: "block", reason: "Banned" } }),
    );
    expect((await checkOffline(await pass("abc", NOW.getTime() / 1000 - 1), p, NOW)).status).toBe("expired");
    expect((await checkOffline(await pass("never-seen"), p, NOW)).status).toBe("unknown");
    expect((await checkOffline(await pass("in"), p, NOW)).status).toBe("inside");
    expect((await checkOffline(await pass("bad"), p, NOW)).status).toBe("blocked");
  });

  it("applies an invite's window and daily hours (IST) and needs consent", async () => {
    const inv = (over: Partial<OfflineEntry>) => entry("", { kind: "invite", state: "invite", ...over });
    const p = await packWith(
      { ...inv({ valid_from: "2026-11-20T08:00:00Z" }), h: await sha("later") },
      { ...inv({ daily_start_time: "14:00:00", daily_end_time: "18:00:00" }), h: await sha("afternoon") },
      { ...inv({ daily_start_time: "09:00:00", daily_end_time: "17:00:00" }), h: await sha("office") },
      { ...inv({ consented: false }), h: await sha("noconsent") },
    );
    expect((await checkOffline(await pass("later"), p, NOW)).status).toBe("not_yet");
    expect((await checkOffline(await pass("afternoon"), p, NOW)).status).toBe("outside_hours");
    expect((await checkOffline(await pass("office"), p, NOW)).status).toBe("ok");
    expect((await checkOffline(await pass("noconsent"), p, NOW)).status).toBe("no_consent");
  });
});
