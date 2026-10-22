import type { Locator, Page } from "@playwright/test";
import type { Api } from "../../helpers/api";
import { expect, test, uid, usePersona } from "../../helpers/fixtures";
import { PASSWORD } from "../../helpers/personas";
import { createThrowawayAgent, openSettings, snapshotSettings } from "../../helpers/settings";

const ACCOUNT = "Email Account";

usePersona("admin");

test("owned mailbox connection reports unavailable without asking for vendor credentials", async ({ page }) => {
  await page.goto("/helpdesk/admin/email-accounts");
  await page.getByLabel("Owned mailbox address").fill("support@example.test");
  await page.getByRole("button", { name: "Connect mailbox", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("not available yet");
  await expect(page.getByRole("textbox", { name: /Password|Server|API Key/ })).toHaveCount(0);
});

const NOTIFICATIONS = [
  { label: "Acknowledgement", enabled: "send_acknowledgement_email", content: "acknowledgement_email_content" },
  { label: "Share feedback", enabled: "enable_email_ticket_feedback", content: "feedback_email_content" },
];

test("each notification saves its content and switch, and share feedback its status", async ({ page, api }) => {
  const fields = NOTIFICATIONS.flatMap((n) => [n.enabled, n.content]);
  const restore = await snapshotSettings(api, [...fields, "send_email_feedback_on_status"]);
  const before = await api.get("HD Settings", "HD Settings");
  try {
    await page.goto("/helpdesk/tickets");
    const dialog = await openSettings(page, "Email Notifications");
    for (const notification of NOTIFICATIONS) {
      const content = `<p>E2E ${notification.label} ${uid()}</p>`;
      await openNotification(dialog, notification.label);
      if (notification.label === "Share feedback") {
        await dialog.getByRole("combobox", { name: /On ticket status/ }).click();
        await page.getByRole("option", { name: "Resolved" }).click();
      }
      await dialog.getByRole("textbox", { name: /Email Content/ }).fill(content);
      await dialog.getByRole("switch", { name: "Enabled" }).click();
      await dialog.getByRole("button", { name: "Save", exact: true }).click();
      await expect.poll(() => setting(api, notification.content)).toBe(content);
      expect(await setting(api, notification.enabled)).toBe(before[notification.enabled] ? 0 : 1);
      await dialog.getByRole("button", { name: "back to email event list" }).click();
    }
    expect(await setting(api, "send_email_feedback_on_status")).toBe("Resolved");
  } finally {
    await restore();
  }
});

test("notification content resets to the default, and leaving unsaved edits asks first", async ({ page, api }) => {
  await page.goto("/helpdesk/tickets");
  const dialog = await openSettings(page, "Email Notifications");
  await openNotification(dialog, "Acknowledgement");
  const content = dialog.getByRole("textbox", { name: /Email Content/ });
  const reset = dialog.getByRole("button", { name: "Reset Content" });
  await content.fill("<p>E2E draft that is never saved</p>");
  await expect(dialog.getByText("Unsaved", { exact: true })).toBeVisible();

  await reset.click();
  await page.getByRole("dialog", { name: "Reset content" }).getByRole("button", { name: "Confirm" }).click();
  await expect(reset).toBeDisabled();
  await expect(content).not.toHaveValue("<p>E2E draft that is never saved</p>");

  await content.fill("<p>E2E second draft</p>");
  await dialog.getByRole("button", { name: "back to email event list" }).click();
  await page.getByRole("dialog", { name: "Unsaved changes" }).getByRole("button", { name: "Confirm" }).click();
  await expect(dialog.getByRole("heading", { name: "Email notifications", level: 1 })).toBeVisible();
  expect(await setting(api, "acknowledgement_email_content")).not.toContain("E2E second draft");
});

test("an admin links and unlinks an outgoing email account", async ({ page, api }) => {
  const before = (await api.get("User", "Administrator")).user_emails;
  try {
    await page.goto("/helpdesk/tickets");
    const dialog = await openSettings(page, / Profile$/);
    await dialog.getByRole("button", { name: "Configure" }).click();
    await linkEmailAccount(page, dialog);
    await expect.poll(() => linkedAccounts(api, "Administrator")).toContain("E2E Support");

    await dialog.getByText("E2E Support", { exact: true }).locator("xpath=..").getByRole("button", { name: "Remove" }).click();
    await dialog.getByRole("button", { name: "Update" }).click();
    await expect.poll(() => linkedAccounts(api, "Administrator")).not.toContain("E2E Support");
  } finally {
    await api.update("User", "Administrator", { user_emails: before });
  }
});

test("a plain agent links an outgoing email account", async ({ page, api }) => {
  // User.user_emails is permlevel 1, so an Agent's save silently drops the row.
  const email = `e2e-link-${uid()}@example.com`;
  await createThrowawayAgent(api, email, PASSWORD);
  await page.context().clearCookies();
  await page.request.post("/api/method/login", { form: { usr: email, pwd: PASSWORD } });
  await page.goto("/helpdesk/tickets");
  const dialog = await openSettings(page, / Profile$/);
  await dialog.getByRole("button", { name: "Configure" }).click();
  await linkEmailAccount(page, dialog);
  await expect.poll(() => linkedAccounts(api, email)).toEqual(["E2E Support"]);
});

async function linkEmailAccount(page: Page, dialog: Locator) {
  await dialog.getByRole("button", { name: "Add Email" }).click();
  await page.getByRole("option", { name: /E2E Support/ }).click();
  await dialog.getByRole("button", { name: "Update" }).click();
}

async function linkedAccounts(api: Api, user: string) {
  return (await api.get("User", user)).user_emails.map((row) => row.email_account);
}

async function openNotification(dialog: Locator, label: string) {
  await dialog.getByRole("button", { name: label, exact: true }).click();
  await expect(dialog.getByRole("heading", { name: label, level: 1 })).toBeVisible();
}

async function setting(api: Api, field: string) {
  return (await api.get("HD Settings", "HD Settings"))[field];
}

