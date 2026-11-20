import { expect, test } from "@playwright/test";
import { readFileSync } from "node:fs";
import { PASSWORD, approvedVisit, guardCheckIn } from "./helpers";

/**
 * Phase 4 for an admin on a laptop: the live dashboard, the visit log with a visit's
 * timeline, a CSV export, the reports page and the evacuation list PDF.
 */
test.use({ viewport: { width: 1280, height: 860 }, isMobile: false, hasTouch: false });

test("admin follows a visit from dashboard to log, export, reports and evacuation", async ({ page, request }) => {
  const name = `Lata Logtest ${Date.now() % 100000}`;
  const { visitId } = await approvedVisit(request, name);
  await guardCheckIn(request, visitId);

  await page.goto("/login");
  await page.getByRole("button", { name: "English" }).click();
  await page.locator("input[autocomplete=username]").fill("admin@kalinga.demo");
  await page.locator("input[type=password]").fill(PASSWORD);
  await page.locator("form button[type=submit]").click();
  await expect(page).toHaveURL(/\/admin$/);

  // Dashboard: live tiles and today's activity.
  const tiles = page.getByTestId("live-tiles");
  await expect(tiles.getByText("People on site")).toBeVisible();
  await expect(page.getByText(name).first()).toBeVisible();

  // Visit log: search, open the visit, read its timeline.
  await page.getByRole("link", { name: "Visit log", exact: true }).click();
  await page.getByLabel("Search").fill(name);
  const row = page.getByTestId("visit-log").locator("tbody tr").filter({ hasText: name });
  await expect(row).toHaveCount(1);
  await expect(row.getByText("On site")).toBeVisible();
  await row.click();
  const detail = page.getByTestId("visit-detail");
  await expect(detail.getByText("Approved", { exact: true })).toBeVisible();
  await expect(detail.getByText(/Ramesh Behera via web/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(detail).toBeHidden();
  await expect(page).toHaveURL(/[?&]q=Lata/); // the export uses what the screen shows

  // Export what's on screen as CSV.
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "CSV" }).click()]);
  expect(download.suggestedFilename()).toMatch(/^visits-\d{8}-\d{4}\.csv$/);
  const csv = readFileSync((await download.path())!, "utf-8");
  expect(csv).toContain(name);
  const lines = csv.split(/\r?\n/).filter(Boolean);
  expect(lines, lines.slice(0, 4).join("\n")).toHaveLength(2); // header + the one match

  // Reports render for the default 30 days.
  await page.getByRole("link", { name: "Reports", exact: true }).click();
  await expect(page.getByTestId("reports").getByText("Visits per day")).toBeVisible();
  await expect(page.getByText("When people arrive")).toBeVisible();

  // Evacuation list: the visitor is on it, and the PDF downloads.
  await page.getByRole("link", { name: "Evacuation", exact: true }).click();
  await expect(page.getByRole("cell", { name: new RegExp(name) })).toBeVisible();
  const [pdf] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Download PDF" }).click()]);
  expect(pdf.suggestedFilename()).toMatch(/^evacuation-.*\.pdf$/);
  expect(readFileSync((await pdf.path())!).subarray(0, 4).toString()).toBe("%PDF");
});
