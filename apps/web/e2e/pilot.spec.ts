import { test, expect } from "@playwright/test";
test("agent can schedule outreach and stop it after a reply", async ({
  page,
}) => {
  const key = process.env.E2E_ACCESS_KEY;
  test.skip(
    !key,
    "Set E2E_ACCESS_KEY to a running demo backend administrator key.",
  );
  const leadName = `Browser Pilot ${Date.now()}`;
  await page.goto("/");
  await page.getByLabel("Personal access key").fill(key!);
  await page.getByRole("button", { name: "Open workspace" }).click();
  await expect(page.getByText("DEMO · NO REAL SENDS")).toBeVisible();
  await page.getByRole("button", { name: "Sequences", exact: true }).click();
  await page.getByRole("button", { name: "New sequence", exact: true }).click();
  await page.getByLabel("Sequence name").fill(`Browser sequence ${Date.now()}`);
  await page.getByLabel("Wait after previous step (minutes)").fill("60");
  await page
    .getByRole("button", { name: "Save sequence", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Overview", exact: true }).click();
  await page.getByRole("button", { name: "Add lead", exact: true }).click();
  await page.getByLabel("Full name").fill(leadName);
  await page
    .getByLabel("Phone", { exact: false })
    .fill(`+1555${String(Date.now()).slice(-7)}`);
  await page.getByLabel("Lead has agreed to SMS follow-ups").check();
  await page.getByLabel("Lead has agreed to AI voice calls").check();
  await page
    .getByLabel("Consent record")
    .fill("Synthetic test lead, explicit demo consent.");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Add lead", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByLabel("Search leads").fill(leadName);
  await page
    .getByRole("button", { name: new RegExp(leadName) })
    .first()
    .click();
  await page.getByRole("button", { name: "Send SMS", exact: true }).click();
  await page
    .getByLabel("Message", { exact: true })
    .fill("Hello from the browser pilot.");
  await page.getByRole("button", { name: "Send message", exact: true }).click();
  await expect(
    page.getByText("Hello from the browser pilot.", { exact: true }).first(),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Schedule follow-up", exact: true })
    .click();
  await page
    .getByRole("dialog")
    .getByLabel("Sequence", { exact: true })
    .selectOption({ index: 1 });
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Schedule follow-up", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Resume", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Resume", exact: true }).click();
  await page.getByRole("button", { name: "AI call", exact: true }).click();
  await page.getByRole("button", { name: "Start call", exact: true }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await page.getByRole("button", { name: "Simulate reply" }).click();
  await page.getByLabel("Lead reply", { exact: true }).fill("STOP");
  await page.getByRole("button", { name: "Record demo reply" }).click();
  await expect(page.locator(".badge.opted_out")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Send SMS", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Schedule follow-up", exact: true }),
  ).toBeDisabled();
  await page.screenshot({
    path: "test-results/lead-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "test-results/lead-mobile.png",
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
