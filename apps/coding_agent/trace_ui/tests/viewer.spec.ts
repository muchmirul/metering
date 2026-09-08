import { test, expect } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

let process: ChildProcessWithoutNullStreams;
let ready: {
  url: string;
  ids: { seed: string; a: string; b: string; c: string };
};
const root = fileURLToPath(new URL("../../../../", import.meta.url));
const key = (value: string) => Buffer.from(value).toString("base64url");

test.beforeAll(async () => {
  process = spawn(
    `${root}/.venv/bin/python`,
    ["tests/trace_browser_fixture.py"],
    { cwd: root },
  );
  ready = await new Promise((resolve, reject) => {
    let buffer = "",
      errors = "";
    const timer = setTimeout(
      () => reject(new Error(`Fixture timed out: ${errors}`)),
      45000,
    );
    process.stderr.on("data", (chunk) => {
      errors += chunk.toString();
    });
    process.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    process.on("exit", (code) => {
      clearTimeout(timer);
      if (!buffer.includes("\n"))
        reject(new Error(`Fixture exited ${code}: ${errors}`));
    });
    process.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      if (buffer.includes("\n")) {
        clearTimeout(timer);
        resolve(JSON.parse(buffer.split("\n")[0]));
      }
    });
  });
});
test.afterAll(async () => {
  if (process?.exitCode === null) {
    process.kill("SIGTERM");
    await new Promise<void>((resolve) => process.once("exit", () => resolve()));
  }
});

test("real browser traces Git files, inert source, deleted versions, and exact downloads", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(ready.url);
  await expect(page.locator("#inspecting")).toHaveText("Inspecting S0");
  await expect(page.locator("#graph canvas").first()).toBeVisible();
  await page.selectOption("#candidate", ready.ids.a);
  await expect(page.locator("#inspecting")).toHaveText("Inspecting S3a");
  await page.selectOption("#file-mode", "all");
  await expect(page.locator("#busy")).toBeHidden();
  await page.getByRole("button", { name: "Fit graph", exact: true }).click();
  // Read the pinned library's rendered coordinates, then exercise an actual pointer click.
  const point = await page
    .locator("#graph")
    .evaluate(
      (container, id) =>
        (container as any)._cyreg.cy.getElementById(id).renderedPosition(),
      `file:${ready.ids.a}:${key("src/merge.py")}`,
    );
  await page.locator("#graph").click({ position: point });
  await expect(page.locator(".source-code")).toContainText("line one");
  await page.screenshot({
    path: "test-results/trace-viewer-file-graph.png",
    fullPage: true,
  });
  await page.locator("#search").fill("S1b");
  expect(
    await page
      .locator("#graph")
      .evaluate((container) =>
        (container as any)._cyreg.cy
          .nodes()
          .map((node: any) => node.data("label").split("\n")[0]),
      ),
  ).toEqual(["S0", "S1b"]); // Keep the match's actual ancestors as context.
  await page.locator("#search").fill("");
  const zoom = await page
    .locator("#graph")
    .evaluate((container) => (container as any)._cyreg.cy.zoom());
  await page.locator("#graph").hover();
  await page.mouse.wheel(0, -240);
  await expect
    .poll(() =>
      page
        .locator("#graph")
        .evaluate((container) => (container as any)._cyreg.cy.zoom()),
    )
    .toBeGreaterThan(zoom);
  await page.locator(`[data-path-id="${key("evil.html")}"]`).click();
  await expect(page.locator(".source-code")).toContainText(
    "<script>window.CANDIDATE_EXECUTED=true</script>",
  );
  expect(
    await page.evaluate(() => (window as any).CANDIDATE_EXECUTED),
  ).toBeUndefined();
  await page.locator(`[data-path-id="${key("src/merge.py")}"]`).click();
  const downloadPromise = page.waitForEvent("download");
  await page
    .getByRole("button", { name: "Download exact bytes", exact: true })
    .click();
  const file = await downloadPromise;
  expect(await readFile((await file.path())!)).toEqual(
    Buffer.from("line one\r\nline two"),
  );
  await page
    .getByRole("button", { name: "Trace this file", exact: true })
    .click();
  await expect(page.locator("#graph-title")).toHaveText(
    "Exact-path file history",
  );
  const traceDownload = page.waitForEvent("download");
  await page.selectOption("#export", "trace");
  const trace = JSON.parse(
    await readFile((await (await traceDownload).path())!, "utf8"),
  );
  expect(
    trace.items.find((row: any) => row.candidate_id === ready.ids.b).file,
  ).toBeNull();
  expect(
    trace.items.find((row: any) => row.candidate_id === ready.ids.a).change,
  ).toBe("added");
  const seed = await page.locator("#graph").evaluate((container) =>
    (container as any)._cyreg.cy
      .nodes()
      .filter((node: any) => node.data("label").startsWith("S0\n"))[0]
      .renderedPosition(),
  );
  await page.locator("#graph").click({ position: seed });
  await expect(page.locator("#inspecting")).toHaveText("Inspecting S0");
  await expect(page.locator("#detail .notice")).toContainText(
    "exact path is absent",
  );
  await page.selectOption("#candidate", ready.ids.b);
  await page.locator(`[data-path-id="${key("src/merge.py")}"]`).click();
  await expect(page.locator("#detail .notice")).toContainText(
    "Deleted from S4a",
  );
  await page.getByRole("button", { name: "Diff", exact: true }).click();
  await expect(page.locator(".source-code")).toContainText("deleted file mode");
  await page
    .getByRole("button", { name: "Inspect inferred renames", exact: true })
    .click();
  await expect(page.locator("#detail")).toContainText("inferred-only");
  await expect(page.locator("#detail")).toContainText("src/renamed.py");
  expect(errors).toEqual([]);
  await page.screenshot({
    path: "test-results/trace-viewer-files.png",
    fullPage: true,
  });
});

test("paging, pending attempts, exports, archive views, deep links and reload", async ({
  page,
}) => {
  await page.goto(ready.url);
  await expect(page.locator("#inspecting")).toHaveText("Inspecting S0");
  await page.selectOption("#candidate", ready.ids.c);
  await page
    .locator("#file-pages")
    .getByRole("button", { name: "Next page" })
    .click();
  await page.locator(`[data-path-id="${key("bulk/104.txt")}"]`).click();
  await expect(page.locator(".source-code")).toHaveText("bulk file 104");
  await page.reload();
  await expect(page.locator("#inspecting")).toHaveText("Inspecting S5a");
  await expect(page.locator(".source-code")).toHaveText("bulk file 104");
  await page
    .getByRole("button", { name: "Loops / attempts", exact: true })
    .click();
  await page.selectOption("#loop-select", "SR4");
  await expect(page.locator("#loop-events")).toContainText(
    "failed (diagnostic-only)",
  );
  await expect(page.locator("#loop-events")).toContainText(
    "no child association inferred",
  );
  await page.getByRole("button", { name: "Close", exact: true }).click();
  const csvDownload = page.waitForEvent("download");
  await page.selectOption("#export", "csv");
  const csv = await readFile((await (await csvDownload).path())!, "utf8");
  expect(csv).toContain("S5a");
  expect(csv).toContain(ready.ids.c);
  await page.selectOption("#archive", { index: 1 });
  await expect(page.locator("#graph-note")).toContainText("not rewound");
  await page.selectOption("#archive", { index: 0 });
  const imageDownload = page.waitForEvent("download");
  await page.selectOption("#export", "png");
  const image = await readFile((await (await imageDownload).path())!);
  expect(image.subarray(1, 4).toString()).toBe("PNG");
  await page.setViewportSize({ width: 600, height: 900 });
  await expect(page.locator("#graph canvas").first()).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBeTruthy();
  await page.route("**/api/graph?*", (route) =>
    route.fulfill({
      status: 400,
      contentType: "application/json",
      body: JSON.stringify({ error: "simulated mid-append read" }),
    }),
  );
  await page
    .getByRole("button", { name: "Refresh evidence", exact: true })
    .click();
  await expect(page.locator("#error")).toContainText(
    "simulated mid-append read",
  );
  await page.unroute("**/api/graph?*");
  await page.getByRole("button", { name: "Source", exact: true }).click();
  await expect(page.locator(".source-code")).toHaveText("bulk file 104");
  await page
    .getByRole("button", { name: "Refresh evidence", exact: true })
    .click();
  await expect(page.locator("#inspecting")).toHaveText("Inspecting S5a");
  await expect(page.locator("#error")).toBeHidden();
});

test("a page without the capability receives no candidate evidence", async ({
  page,
}) => {
  await page.goto(ready.url.split("#")[0]);
  await expect(page.locator("#error")).toContainText(
    "Missing viewer capability",
  );
  await expect(page.locator("#candidate option")).toHaveCount(0);
});
