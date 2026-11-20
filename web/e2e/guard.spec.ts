import { expect, test } from "@playwright/test";
import { API, admin, approvedVisit, guardLogin, inbox, randomPhone } from "./helpers";

/**
 * Phase 3 at the gate, on a phone-sized screen:
 * - a visitor's approved pass is checked at the gate, checked in, then out while the
 *   guard's phone is offline (synced when it's back);
 * - a pre-approved guest opens their pass, accepts the notice, and is let in by scan.
 */

test("guard scans an approved pass, checks in, and checks out while offline", async ({ page, request, context }) => {
  const name = `Gita Gatetest ${Date.now() % 10000}`;
  const { pass } = await approvedVisit(request, name);
  await guardLogin(page);

  await page.getByTestId("scan-manual").fill(pass);
  await page.getByRole("button", { name: "Check pass" }).click();
  const result = page.getByTestId("scan-result");
  await expect(result).toHaveAttribute("data-result", "ok");
  await expect(result.getByText(name)).toBeVisible();
  await result.getByRole("button", { name: "Check in" }).click();
  await expect(result.getByRole("status")).toHaveText(/Checked in/);

  await page.getByRole("tab", { name: /Visitors/ }).click();
  await page.getByPlaceholder(/Find by name/).fill(name);
  const row = page.getByTestId("visitor-row").filter({ hasText: name });
  await expect(row).toHaveAttribute("data-status", "checked_in");

  // The gate's Wi-Fi drops: the check-out is kept on the phone…
  await context.setOffline(true);
  await row.getByRole("button", { name: "Check out" }).click();
  await expect(page.getByText(/Offline/)).toBeVisible();
  await expect(page.getByText(/1 action waiting to sync/)).toBeVisible();
  await expect(row).toHaveAttribute("data-status", "checked_out");
  await expect(row.getByText("Waiting to sync")).toBeVisible();

  // …and sent when it comes back.
  await context.setOffline(false);
  await expect(page.getByText(/waiting to sync/)).toBeHidden({ timeout: 20_000 });
  await expect(row).toHaveAttribute("data-status", "checked_out");
  await expect(row.getByText(/Left /)).toBeVisible();
  const scan2 = await (await page.request.get(`${API}/public/passes/${pass}`)).json();
  expect(scan2.state).toBe("used");
});

test("pre-approved guest accepts the notice on their pass and is let in by scan", async ({ page, request, browser }) => {
  const { hq, h } = await admin(request);
  const users = await (await request.get(`${API}/users?q=Meera`, { headers: h })).json();
  const guestPhone = randomPhone();
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata" }).format(new Date());
  const inv = await request.post(`${API}/invites`, {
    headers: h,
    data: { site_id: hq.id, host_id: users.items[0].id, kind: "single", title: "E2E board meeting", date: today, start_time: "00:00", end_time: "23:59", guests: [{ name: "Vera Vip", phone: guestPhone, company: "Board" }] },
  });
  expect(inv.status()).toBe(201);
  const link = (await inbox(request, `+91${guestPhone}`, "invite")).text.match(/https?:\/\/\S+\/p\/(\S+)/)!;

  // The guest, on their own phone.
  const guest = await (await browser.newContext()).newPage();
  await guest.goto(new URL(link[0]).pathname);
  await expect(guest.getByTestId("pass-qr")).toHaveCount(0);
  await guest.getByTestId("pass-consent").getByRole("button").click();
  await expect(guest.getByTestId("pass-qr").locator("svg")).toBeVisible();

  // The guard scans it (the QR holds the bare token).
  await guardLogin(page);
  await page.getByTestId("scan-manual").fill(link[1]);
  await page.getByRole("button", { name: "Check pass" }).click();
  const result = page.getByTestId("scan-result");
  await expect(result).toHaveAttribute("data-result", "ok");
  await expect(result.getByText("Pre-approved invite")).toBeVisible();
  await result.getByRole("button", { name: "Check in" }).click();
  await expect(result.getByRole("status")).toHaveText(/Checked in/);

  // The guest's pass follows (it refreshes every 30 s; reload to see it now).
  await guest.reload();
  await expect(guest.getByRole("status").filter({ hasText: "Checked in" })).toBeVisible();
});
