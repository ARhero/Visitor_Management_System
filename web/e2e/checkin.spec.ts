import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

/**
 * The whole Phase 2 loop on a phone-sized screen:
 * scan gate QR → OTP on (mock) WhatsApp → details → selfie → consent → waiting →
 * host answers on WhatsApp / web link → visitor's screen updates live → pass.
 */

const API = "/api/v1";
// 1×1 PNG: enough for the camera input (the app re-encodes it).
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

interface Msg { id: string; template: string; phone: string; text: string; buttons: { id: string; title: string }[] }

async function gateToken(request: APIRequestContext): Promise<string> {
  const login = await request.post(`${API}/auth/login`, { data: { identifier: "admin@kalinga.demo", password: process.env.SEED_PASSWORD ?? "demo-password-123" } });
  expect(login.ok(), "seeded admin login (run scripts.seed first)").toBeTruthy();
  const { access_token } = await login.json();
  const sites = await (await request.get(`${API}/sites`, { headers: { Authorization: `Bearer ${access_token}` } })).json();
  const hq = sites.find((s: { name: string }) => s.name === "Bhubaneswar HQ");
  return hq.gates[0].qr_token;
}

async function inbox(request: APIRequestContext, phone: string, template: string): Promise<Msg> {
  for (let i = 0; i < 20; i++) {
    const msgs: Msg[] = await (await request.get(`${API}/dev/whatsapp/messages?phone=${encodeURIComponent(phone)}`)).json();
    const m = msgs.find((x) => x.template === template);
    if (m) return m;
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`no ${template} message for ${phone}`);
}

function randomPhone() {
  return `9${Math.floor(100000000 + Math.random() * 899999999)}`;
}

async function checkIn(page: Page, request: APIRequestContext, opts: { host: string; hostPhone: string; name: string }) {
  const token = await gateToken(request);
  const phone = randomPhone();
  await page.goto(`/v/${token}`);
  await expect(page.getByText("Bhubaneswar HQ · Main Gate")).toBeVisible();

  await page.locator("input[type=tel]").fill(phone);
  await page.locator("button[type=submit]").click();
  const otp = await inbox(request, `+91${phone}`, "otp");
  await page.locator("input[autocomplete=one-time-code]").fill(otp.text.match(/\d{6}/)![0]); // auto-submits

  await page.locator("input[autocomplete=name]").fill(opts.name);
  await page.locator("input[autocomplete=organization]").fill("Playwright Labs");
  await page.locator("input[autocomplete=off]").first().fill(opts.host.split(" ")[0]);
  await page.getByRole("button", { name: new RegExp(opts.host) }).click();
  await page.locator("label:has(input[name=purpose])").first().click();
  await page.locator("form button[type=submit]").click();

  await page.getByTestId("photo-input").setInputFiles({ name: "me.png", mimeType: "image/png", buffer: PNG });
  await expect(page.locator("img[src^='blob:']")).toBeVisible();
  await page.locator("main button").last().click(); // Continue

  await page.locator("input[type=checkbox]").check();
  await page.locator("main button").last().click(); // Check in / चेक-इन करें
  await expect(page).toHaveURL(/\/visit\//);
  return `+91${phone}`;
}

test("visitor checks in, host approves on WhatsApp, pass appears live", async ({ page, request }) => {
  await checkIn(page, request, { host: "Meera Iyer", hostPhone: "+919861000018", name: "Esha Tester" });
  await expect(page.getByTestId("visit-status")).toHaveAttribute("data-status", "pending");
  await expect(page.getByText("Waiting for Meera Iyer")).toBeVisible();

  // Meera taps "Approve" in WhatsApp (mock inbox → same webhook processing).
  const req = await inbox(request, "+919861000018", "visit_request");
  expect(req.text).toContain("Esha Tester");
  const approve = req.buttons.find((b) => b.id.endsWith("|approve"))!;
  const r = await request.post(`${API}/dev/whatsapp/messages/${req.id}/reply`, { data: { button_id: approve.id } });
  expect((await r.json()).results[0]).toBe("approve:approved");

  // No reload: the status page updates by itself and shows the pass with its QR.
  await expect(page.getByTestId("visit-status")).toHaveAttribute("data-status", "approved", { timeout: 15_000 });
  await expect(page.getByText("You're approved")).toBeVisible();
  await expect(page.getByTestId("pass-qr").locator("svg")).toBeVisible();
  await expect(page.getByRole("status").filter({ hasText: "Valid" })).toBeVisible();
});

test("Hindi visitor; host declines from the web link with a message", async ({ page, request }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "हिन्दी" }).click();
  await checkIn(page, request, { host: "Arjun Nair", hostPhone: "+919861000013", name: "हिमांशु परीक्षक" });
  await expect(page.getByText("Arjun Nair के जवाब का इंतज़ार")).toBeVisible();

  const req = await inbox(request, "+919861000013", "visit_request");
  const link = req.text.match(/https?:\/\/\S+\/r\/\S+/)![0];
  const host = await page.context().newPage();
  await host.goto(new URL(link).pathname);
  await expect(host.getByText("हिमांशु परीक्षक")).toBeVisible();
  await host.getByRole("button", { name: "मना करें" }).click();
  await host.locator("#msg").fill("आज मीटिंग नहीं हो पाएगी");
  await host.getByRole("button", { name: "मना करें" }).click();
  await expect(host.getByText("अस्वीकृत। आगंतुक को सूचित कर दिया गया है।")).toBeVisible();

  await expect(page.getByTestId("visit-status")).toHaveAttribute("data-status", "rejected", { timeout: 15_000 });
  await expect(page.getByText("आज मीटिंग नहीं हो पाएगी")).toBeVisible();
});
