import { describe, expect, it, vi } from "vitest";
import { withPending, type GuardCard, type GuardQueue } from "@/features/guard/guardApi";
import { ApiError } from "./api";
import { memoryStore, Outbox, type QueuedAction } from "./offlineQueue";

const action = (id: string, kind: QueuedAction["kind"] = "check-in", at = "2026-11-19T10:00:00Z") => ({
  id,
  visitId: `v-${id}`,
  kind,
  label: `Visitor ${id}`,
  occurredAt: at,
  body: {},
});

const offline = () => Promise.reject(new TypeError("Failed to fetch"));

describe("Outbox", () => {
  it("sends straight away when online", async () => {
    const send = vi.fn().mockResolvedValue({ ok: 1 });
    const box = new Outbox(memoryStore(), send);
    expect(await box.submit(action("a"))).toEqual({ ok: 1 });
    expect(box.pending()).toHaveLength(0);
  });

  it("keeps the tap when the network fails and replays it with the same key", async () => {
    const send = vi.fn().mockImplementationOnce(offline).mockResolvedValue({});
    const box = new Outbox(memoryStore(), send);
    expect(await box.submit(action("a"))).toBeNull();
    expect(box.pending().map((p) => p.id)).toEqual(["a"]);

    await box.flush();
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1][0].id).toBe("a"); // same Idempotency-Key
    expect(box.pending()).toHaveLength(0);
  });

  it("replays oldest first and stops at the first network failure", async () => {
    const order: string[] = [];
    let fail = true;
    const send = vi.fn(async (a: QueuedAction) => {
      if (fail) return offline();
      order.push(a.id);
    });
    const box = new Outbox(memoryStore(), send);
    await box.submit(action("late", "check-out", "2026-11-19T11:00:00Z"));
    await box.submit(action("early", "check-in", "2026-11-19T10:00:00Z"));
    await box.flush(); // still offline: nothing lost
    expect(box.pending()).toHaveLength(2);
    expect(box.pending()[0].attempts).toBe(1);

    fail = false;
    await box.flush();
    expect(order).toEqual(["early", "late"]);
  });

  it("drops actions the server refuses and reports them", async () => {
    const send = vi.fn().mockImplementationOnce(offline).mockRejectedValue(new ApiError(409, "invalid_transition", "This visit is already checked out"));
    const box = new Outbox(memoryStore(), send);
    await box.submit(action("a", "check-out"));
    await box.flush();
    expect(box.pending()).toHaveLength(0);
    expect(box.failed).toHaveLength(1);
    expect(box.failed[0].error).toMatch(/already checked out/);
    box.dismissFailed();
    expect(box.failed).toHaveLength(0);
  });

  it("throws server errors to the caller instead of queueing them", async () => {
    const box = new Outbox(memoryStore(), vi.fn().mockRejectedValue(new ApiError(403, "blocked", "Entry not allowed")));
    await expect(box.submit(action("a"))).rejects.toThrow("Entry not allowed");
    expect(box.pending()).toHaveLength(0);
  });

  it("treats an unreachable server as offline", async () => {
    const box = new Outbox(memoryStore(), vi.fn().mockRejectedValue(new ApiError(502, "server_unavailable", "down")));
    expect(await box.submit(action("a"))).toBeNull();
    expect(box.pending()).toHaveLength(1);
  });
});

const card = (id: string, status: string, extra: Partial<GuardCard> = {}): GuardCard =>
  ({ id, status, accompanying_count: 0, visitor_name: id, ...extra }) as GuardCard;

describe("withPending", () => {
  const q: GuardQueue = {
    site_id: "s",
    awaiting: [],
    expected: [card("a", "approved", { accompanying_count: 2 })],
    on_site: [card("b", "checked_in")],
    left: [],
    alerts: [],
    invites: [],
    people_on_site: 1,
  };

  it("shows unsynced taps as done", () => {
    const out = withPending(q, [
      { ...action("1"), visitId: "a", attempts: 0 },
      { ...action("2", "check-out"), visitId: "b", attempts: 0 },
    ]);
    expect(out.expected).toHaveLength(0);
    expect(out.on_site.map((c) => c.id)).toEqual(["a"]);
    expect(out.left.map((c) => c.id)).toEqual(["b"]);
    expect(out.people_on_site).toBe(3);
    expect([...out.syncing]).toEqual(["a", "b"]);
  });

  it("applies check-in then check-out of the same visit in order", () => {
    const out = withPending(q, [
      { ...action("1"), visitId: "a", attempts: 0 },
      { ...action("2", "check-out"), visitId: "a", attempts: 0 },
    ]);
    expect(out.left.map((c) => c.id)).toEqual(["a"]);
    expect(out.on_site.map((c) => c.id)).toEqual(["b"]);
  });
});
