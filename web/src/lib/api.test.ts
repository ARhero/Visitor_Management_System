import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, errorMessage, setAccessToken } from "./api";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

afterEach(() => {
  vi.restoreAllMocks();
  setAccessToken(null);
});

describe("api()", () => {
  it("refreshes once on 401 and retries with the new token", async () => {
    setAccessToken("old");
    const seen: (string | null)[] = [];
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) return json(200, { access_token: "new" });
      seen.push(new Headers(init?.headers).get("Authorization"));
      return seen.length === 1 ? json(401, { error: { code: "unauthorized", message: "x" } }) : json(200, { ok: true });
    });
    await expect(api("/sites")).resolves.toEqual({ ok: true });
    expect(seen).toEqual(["Bearer old", "Bearer new"]);
  });

  it("de-duplicates concurrent refreshes", async () => {
    setAccessToken("old");
    let refreshes = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input).endsWith("/auth/refresh")) {
        refreshes++;
        return json(200, { access_token: "new" });
      }
      const auth = new Headers(init?.headers).get("Authorization");
      return auth === "Bearer new" ? json(200, {}) : json(401, {});
    });
    await Promise.all([api("/a"), api("/b"), api("/c")]);
    expect(refreshes).toBe(1);
  });

  it("raises ApiError with the server's code and a readable field message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      json(422, { error: { code: "validation_error", message: "Some fields are invalid",
        details: [{ loc: ["body", "phone"], msg: "Value error, Invalid phone number" }] } }),
    );
    const err = (await api("/users", { method: "POST", body: {} }).catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("validation_error");
    expect(errorMessage(err)).toBe("phone: Invalid phone number");
  });
});
