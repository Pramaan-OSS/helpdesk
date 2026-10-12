// Headless smoke check of the applied design system (owner instruction:
// Playwright headless only; no visible browser). Run with the repo's Playwright:
//   npx playwright test e2e/smoke.design.spec.ts
import { expect, test } from "@playwright/test";

const BASE = process.env.BASE_URL || "http://127.0.0.1:18008";

test("login page uses the design system ground, faces and ink", async ({ page }) => {
  await page.goto(BASE + "/login");
  await expect(page).toHaveTitle(/Sign in · Pramaan Helpdesk/);
  const ground = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(ground).toBe("rgb(237, 237, 237)");
  const headingFace = await page.evaluate(() => getComputedStyle(document.querySelector("h1")).fontFamily);
  expect(headingFace).toContain("Fraunces");
  const buttonColor = await page.evaluate(() => {
    const button = document.querySelector<HTMLButtonElement>("#login button");
    return button ? getComputedStyle(button).backgroundColor : "";
  });
  expect(buttonColor).toBe("rgba(17, 17, 17, 0.88)");
  await page.screenshot({ path: ".runtime/design-smoke-login.png", fullPage: true });
});

test("no request leaves the origin", async ({ page }) => {
  const outside: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin !== new URL(BASE).origin && !url.protocol.startsWith("data:") && url.protocol !== "blob:") {
      outside.push(request.url());
    }
  });
  await page.goto(BASE + "/login");
  await page.waitForLoadState("networkidle");
  expect(outside).toEqual([]);
});
