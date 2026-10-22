import type { Page } from "@playwright/test";
import { expect, test } from "../../helpers/fixtures";
import { FormScripts, TEMPLATE, ensureTemplate } from "../../helpers/form-script";

const NEW_WITH_TEMPLATE = `/helpdesk/tickets/new/${encodeURIComponent(TEMPLATE)}`;
let scripts: FormScripts;
test.beforeEach(({ api }) => { scripts = new FormScripts(api); });
test.afterEach(async () => { await scripts.removeAll(); });

test("stored JavaScript cannot add actions or make requests on any ticket surface", async ({ pageAs, ticket }) => {
  const body = `window.__unrestrictedScriptRan = true; fetch("/api/method/ping"); return { actions: [{ label: "Unrestricted action", onClick() {} }] };`;
  for (const portal of [false, true]) for (const newPage of [false, true]) await scripts.create(body, { portal, newPage });
  for (const [persona, url] of [["agent", `/helpdesk/tickets/${ticket.name}`], ["customer", `/helpdesk/my-tickets/${ticket.name}`], ["agent", "/helpdesk/tickets/new"], ["customer", "/helpdesk/my-tickets/new"]] as const) {
    const page = await pageAs(persona);
    await page.goto(url);
    await expect(page.locator("#app")).not.toBeEmpty();
    await page.waitForLoadState("networkidle");
    await expect(page.getByRole("button", { name: "Unrestricted action" })).toHaveCount(0);
    expect(await page.evaluate(() => (window as any).__unrestrictedScriptRan)).toBeUndefined();
  }
});

test.describe("local field rules", () => {
  test.beforeEach(async ({ api }) => { await ensureTemplate(api); });
  test("visibility and required fields follow another field", async ({ pageAs }) => {
    const page = await pageAs("agent");
    await page.goto(NEW_WITH_TEMPLATE);
    await expect(field(page, "E2E shown")).toHaveCount(0);
    await expect(field(page, "E2E needed").getByText("*")).toHaveCount(0);
    await pick(page, "E2E trigger", "Show");
    await expect(field(page, "E2E shown")).toBeVisible();
    await expect(field(page, "E2E needed").getByText("*")).toBeVisible();
  });
  test("a read-only rule locks a field", async ({ pageAs }) => {
    const page = await pageAs("agent");
    await page.goto(NEW_WITH_TEMPLATE);
    await pick(page, "E2E trigger", "Show");
    await expect(field(page, "E2E locked").getByRole("textbox")).toBeDisabled();
  });
});
function field(page: Page, label: string) {
  return page.locator(".space-y-1\\.5").filter({ has: page.getByText(new RegExp(`^${label}\\b`)) });
}
async function pick(page: Page, label: string, option: string) {
  await field(page, label).getByRole("combobox").click();
  await page.getByRole("option", { name: option, exact: true }).click();
}
