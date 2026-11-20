import { expect, type APIRequestContext, type Page } from "@playwright/test";

/** Shared by the e2e specs: API shortcuts and sign-in. Needs the seeded demo org. */

export const API = "/api/v1";
export const PASSWORD = process.env.SEED_PASSWORD ?? "demo-password-123";
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");

interface Msg { id: string; template: string; text: string; buttons: { id: string }[]; params?: Record<string, string> }

export async function inbox(request: APIRequestContext, phone: string, template: string): Promise<Msg> {
  for (let i = 0; i < 20; i++) {
    const msgs: Msg[] = await (await request.get(`${API}/dev/whatsapp/messages?phone=${encodeURIComponent(phone)}`)).json();
    const m = msgs.find((x) => x.template === template);
    if (m) return m;
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`no ${template} message for ${phone}`);
}

export const randomPhone = () => `9${Math.floor(100000000 + Math.random() * 899999999)}`;

export async function admin(request: APIRequestContext) {
  const r = await request.post(`${API}/auth/login`, { data: { identifier: "admin@kalinga.demo", password: PASSWORD } });
  expect(r.ok(), "seeded admin login (run scripts.seed first)").toBeTruthy();
  const h = { Authorization: `Bearer ${(await r.json()).access_token}` };
  const sites = await (await request.get(`${API}/sites`, { headers: h })).json();
  return { h, hq: sites.find((s: { name: string }) => s.name === "Bhubaneswar HQ") };
}

/** A visitor checks in through the public API and Meera approves on WhatsApp. */
export async function approvedVisit(request: APIRequestContext, name: string) {
  const { hq, h } = await admin(request);
  const gate = hq.gates[0].qr_token;
  const phone = randomPhone();
  await request.post(`${API}/public/otp/send`, { data: { gate_token: gate, phone } });
  const otp = (await inbox(request, `+91${phone}`, "otp")).text.match(/\d{6}/)![0];
  const vt = (await (await request.post(`${API}/public/otp/verify`, { data: { gate_token: gate, phone, code: otp } })).json()).token;
  const auth = { Authorization: `Bearer ${vt}` };
  const info = await (await request.get(`${API}/public/gates/${gate}`)).json();
  const hosts = await (await request.get(`${API}/public/hosts?q=Meera`, { headers: auth })).json();
  const up = await (await request.post(`${API}/public/uploads`, { headers: auth, multipart: { kind: "selfie", file: { name: "me.png", mimeType: "image/png", buffer: PNG } } })).json();
  const v = await (await request.post(`${API}/public/visits`, {
    headers: auth,
    data: { full_name: name, company: "Gate Test Co", host_id: hosts[0].id, purpose_id: info.purposes[0].id, photo_upload: up.upload_token, consent_notice_id: info.notices.en.id, consent: true },
  })).json();
  // This visitor's own request (other tests may be messaging the same host at once).
  let req: Msg | undefined;
  for (let i = 0; i < 20 && !req; i++) {
    const msgs: Msg[] = await (await request.get(`${API}/dev/whatsapp/messages?phone=%2B919861000018`)).json();
    req = msgs.find((m) => m.template === "visit_request" && m.text.includes(name));
    if (!req) await new Promise((r) => setTimeout(r, 250));
  }
  expect(req, `request message for ${name}`).toBeTruthy();
  const btn = req!.buttons.find((b) => b.id.endsWith("|approve"))!;
  await request.post(`${API}/dev/whatsapp/messages/${req!.id}/reply`, { data: { button_id: btn.id } });
  const st = await (await request.get(`${API}/public/visits/${v.visit_id}`, { headers: { Authorization: `Bearer ${v.status_token}` } })).json();
  return { pass: st.pass.token as string, h, visitId: v.visit_id as string, phone: `+91${phone}` };
}

export async function guardLogin(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "English" }).click();
  await page.locator("input[autocomplete=username]").fill("9861000002");
  await page.locator("input[type=password]").fill(PASSWORD);
  await page.locator("form button[type=submit]").click();
  await expect(page).toHaveURL(/\/guard/);
  await expect(page.getByText("Bhubaneswar HQ")).toBeVisible();
}


/** The seeded guard checks a visit in through the API (scan + check-in). */
export async function guardCheckIn(request: APIRequestContext, visitId: string) {
  const r = await request.post(`${API}/auth/login`, { data: { identifier: "9861000002", password: PASSWORD } });
  const h = { Authorization: `Bearer ${(await r.json()).access_token}` };
  const res = await request.post(`${API}/guard/visits/${visitId}/check-in`, { headers: { ...h, "Idempotency-Key": `e2e-${visitId}` }, data: {} });
  expect(res.ok(), await res.text()).toBeTruthy();
}
