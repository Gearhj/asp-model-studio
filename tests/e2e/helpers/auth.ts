import { expect, type Page } from "@playwright/test";

export type TestUser = { email: string; displayName: string; password: string };

/** Generates a unique throwaway test user so runs never collide with each other or with real accounts. */
export function makeTestUser(slug: string): TestUser {
  const stamp = Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  return {
    email: `e2e-${slug}-${stamp}@atlas-e2e.local`,
    displayName: `E2E ${slug} ${stamp}`,
    password: "AtlasE2ePassw0rd!",
  };
}

export async function registerUser(page: Page, user: TestUser): Promise<void> {
  await page.goto("/register");
  await page.getByLabel("Display Name").fill(user.displayName);
  await page.getByLabel("Email").fill(user.email);
  // The Register page's Password field has helper text inside the same <label>,
  // which becomes part of its accessible name -- match by prefix, not exact text.
  await page.getByLabel(/^Password/).fill(user.password);
  await page.getByLabel("Confirm Password").fill(user.password);
  await page.getByRole("button", { name: "Create Account" }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });
}

export async function loginUser(page: Page, user: Pick<TestUser, "email" | "password">): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("Email").fill(user.email);
  await page.getByLabel(/^Password/).fill(user.password);
  await page.getByRole("button", { name: "Sign In" }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 20_000 });
}

export async function logout(page: Page): Promise<void> {
  await page.request.post("/api/auth/logout").catch(() => undefined);
}
