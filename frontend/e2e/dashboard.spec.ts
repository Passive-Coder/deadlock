import { expect, test } from "@playwright/test";

test("loads the local dashboard and navigates to device resources", async ({
  page,
}) => {
  const health = await page.request.get("/api/health");
  expect(health.ok()).toBeTruthy();
  await expect(health.json()).resolves.toMatchObject({ status: "ok" });

  await page.goto("/");
  await expect(page).toHaveTitle(/DEADLOCK/i);
  await expect(
    page.getByRole("button", { name: "Live monitor", exact: true }),
  ).toBeVisible();

  await page
    .getByRole("button", { name: "Device resources", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Device resources", level: 1 }),
  ).toBeVisible();
});
