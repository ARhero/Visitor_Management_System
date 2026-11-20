import { describe, expect, it } from "vitest";
import { summarize } from "./AuditPage";

describe("audit summarize", () => {
  it("expands nested settings to the keys that changed", () => {
    const s = summarize("org.update", {
      settings: [{ retention_days: 90, approval_timeout_min: 5, max_escalations: 2 }, { retention_days: 120, approval_timeout_min: 5, max_escalations: 2 }],
      branding: [{ primary_color: "#0F4C5C" }, { primary_color: "#123456" }],
    });
    expect(s).toBe("settings.retention_days: 90 → 120 · branding.primary_color: #0F4C5C → #123456");
  });
  it("shows simple values and short lists", () => {
    expect(summarize("user.update", { is_active: [true, false] })).toBe("is_active: true → false");
    expect(summarize("user.create", { roles: ["guard", "host"] })).toBe("roles: guard, host");
  });
  it("caps the number of parts", () => {
    expect(summarize("site.create", { a: 1, b: 2, c: 3, d: 4, e: 5, f: 6 })).toBe("a: 1 · b: 2 · c: 3 · d: 4 · +2 more");
  });
});
