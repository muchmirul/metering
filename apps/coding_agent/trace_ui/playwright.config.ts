import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests",
  workers: 1,
  timeout: 60000,
  use: {
    browserName: "chromium",
    headless: true,
    viewport: { width: 1500, height: 1000 },
    screenshot: "only-on-failure",
  },
  reporter: "list",
});
