import { expect, test, type APIRequestContext } from "@playwright/test";
import { API, approvedVisit, inbox, randomPhone } from "./helpers";

/**
 * Phase 5: a new organization signs up and goes through the setup wizard (ending with
 * the test visit approved on WhatsApp), and a visitor uses the privacy page to see and
 * download their data.
 */

async function approveLatest(request: APIRequestContext, phone: string) {
  const msg = await inbox(request, phone, "visit_request");
  const btn = msg.buttons.find((b) => b.id.endsWith("|approve"))!;
  const r = await request.post(`${API}/dev/whatsapp/messages/${msg.id}/reply`, { data: { button_id: btn.id } });
  expect(r.ok()).toBeTruthy();
}

test.describe("setup wizard", () => {
  test.use({ viewport: { width: 1280, height: 860 }, isMobile: false, hasTouch: false });

  test("a new org goes from sign-up to a test visit approved on WhatsApp", async ({ page, request }) => {
    const n = Date.now() % 1_000_000;
    const adminPhone = randomPhone();
    await page.goto("/signup");
    await page.getByRole("button", { name: "English" }).click();
    await page.getByLabel("Organization name").fill(`Wizard Test ${n}`);
    await page.getByLabel("Your name").fill("Asha Panda");
    await page.getByLabel("Work email").fill(`asha${n}@wizardtest.in`);
    await page.getByLabel("Password").fill("wizard-e2e-password");
    await page.getByRole("button", { name: "Create organization" }).click();
    await expect(page).toHaveURL(/\/admin\/setup/);

    // 1. Organization
    await page.getByLabel("Privacy contact").fill("privacy@wizardtest.in");
    await page.getByRole("button", { name: "Save and continue" }).click();
    // 2. Site
    await expect(page.getByRole("heading", { name: "Add your first site" })).toBeVisible();
    await page.getByLabel("Site name").fill("Cuttack Works");
    await page.getByRole("button", { name: "Add site and continue" }).click();
    // 3. Hosts
    await expect(page.getByRole("heading", { name: "Your hosts" })).toBeVisible();
    await page.getByLabel("Name", { exact: true }).fill("Ravi Behera");
    await page.getByLabel("Mobile number", { exact: true }).fill(randomPhone());
    await page.getByRole("button", { name: "Add host" }).click();
    await expect(page.getByText("1 host so far")).toBeVisible();
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    // 4. Form
    await expect(page.getByRole("heading", { name: "The check-in form" })).toBeVisible();
    await expect(page.getByText("Purposes of visit")).toBeVisible();
    await page.getByRole("button", { name: "Save and continue" }).click();
    // 5. Posters: download one; the step ticks itself.
    await expect(page.getByRole("heading", { name: "Print the QR posters" })).toBeVisible();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Main Gate" }).click();
    expect((await download).suggestedFilename()).toMatch(/^qr-posters-cuttack-works-main-gate\.pdf$/);
    await page.getByRole("button", { name: "Continue", exact: true }).click();
    // 6. Test visit, approved from the (mock) WhatsApp message.
    await expect(page.getByRole("heading", { name: "Send yourself a test visit" })).toBeVisible();
    await page.getByLabel("Your WhatsApp number").fill(adminPhone);
    await page.getByRole("button", { name: "Send test visit" }).click();
    await expect(page.getByText("Waiting for you to tap Approve on WhatsApp")).toBeVisible();
    await approveLatest(request, `+91${adminPhone}`);
    await expect(page.getByText("You're ready for visitors")).toBeVisible({ timeout: 10_000 });

    // The dashboard checklist: only the guard is left.
    await page.getByRole("button", { name: "Go to the dashboard" }).click();
    await expect(page.getByText("6 of 7")).toBeVisible();
    await expect(page.getByText("Add a guard or receptionist")).toBeVisible();
  });
});

test("a visitor sees and downloads their data on the privacy page (Hindi)", async ({ page, request }) => {
  const name = `Priya Privacy ${Date.now() % 100000}`;
  const { phone } = await approvedVisit(request, name);

  await page.goto("/privacy/kalinga-infotech-pvt-ltd");
  await page.getByRole("button", { name: "हिन्दी" }).click();
  await expect(page.getByRole("heading", { name: "आपका विज़िटर डेटा" })).toBeVisible();
  await page.getByRole("textbox").fill(phone.slice(3));
  await page.getByRole("button", { name: "WhatsApp पर कोड भेजें" }).click();
  await expect(page.getByText(/पर WhatsApp से कोड भेजा गया/)).toBeVisible(); // newest code is this one
  const code = (await inbox(request, phone, "otp")).text.match(/\d{6}/)![0];
  await page.getByLabel("6 अंकों का कोड").fill(code);
  await page.getByRole("button", { name: "मेरा डेटा दिखाएँ" }).click();

  await expect(page.getByText(name)).toBeVisible();
  await expect(page.getByText("विज़िट (1)")).toBeVisible();
  // The visit is still open, so erasure waits until they leave.
  await expect(page.getByText(/आपकी एक विज़िट अभी चल रही है/)).toBeVisible();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "मेरा डेटा डाउनलोड करें" }).click();
  expect((await download).suggestedFilename()).toMatch(/^visitor-data-\d{4}-\d{8}\.zip$/);
});
