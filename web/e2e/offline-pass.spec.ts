import { expect, test } from "@playwright/test";
import { API, approvedVisit, guardLogin } from "./helpers";

/**
 * The gate loses its connection: the guard's phone still checks a pass (signature and
 * today's list, both on the device), the check-in waits on the phone, and the server
 * applies it once the connection is back.
 */
test("a pass is checked and checked in with no connection, then synced", async ({ page, request, context }) => {
  const name = `Omkar Offline ${Date.now() % 10000}`;
  const { pass, visitId, h } = await approvedVisit(request, name);

  const packLoaded = page.waitForResponse((r) => r.url().includes("/guard/offline-pack") && r.ok());
  await guardLogin(page);
  await packLoaded;

  await context.setOffline(true);
  await expect(page.getByText(/No connection\. Passes are checked on this phone/)).toBeVisible();
  await page.getByTestId("scan-manual").fill(pass);
  await page.getByRole("button", { name: "Check pass" }).click();
  const sheet = page.getByTestId("offline-result");
  await expect(sheet).toHaveAttribute("data-result", "ok");
  await expect(sheet.getByText(name)).toBeVisible();
  await expect(sheet.getByText("To meet Meera Iyer")).toBeVisible();
  await page.getByTestId("offline-check-in").click();
  await expect(sheet.getByRole("status")).toHaveText(/Checked in: will sync/);

  // A forged pass is caught on the device too.
  await sheet.getByRole("button", { name: "Scan next" }).click();
  await page.getByTestId("scan-manual").fill(pass.slice(0, -6) + "AAAAAA");
  await page.getByRole("button", { name: "Check pass" }).click();
  await expect(page.getByTestId("offline-result")).toHaveAttribute("data-result", "invalid");

  // Nothing reached the server yet...
  let v = await (await request.get(`${API}/guard/visits/${visitId}`, { headers: h })).json();
  expect(v.status).toBe("approved");

  // ...until the connection is back.
  await context.setOffline(false);
  await expect
    .poll(async () => (await (await request.get(`${API}/guard/visits/${visitId}`, { headers: h })).json()).status, { timeout: 20_000 })
    .toBe("checked_in");
  v = await (await request.get(`${API}/guard/visits/${visitId}`, { headers: h })).json();
  expect(v.checked_in_at).toBeTruthy();
});
