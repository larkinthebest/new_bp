import { test, expect } from "@playwright/test";

test("ready sources can be reanalyzed without uploading again", async ({ page }) => {
  let queued = false;
  await page.route("**/api/contents", route => route.fulfill({json: [{
    id: "existing-source", name: "Highlights.mp4", status: queued ? "queued" : "ready",
    progress: queued ? "Queued for reanalysis" : "Ready", segments: 58,
  }]}));
  await page.route("**/api/contents/existing-source/reindex", route => {
    queued = true;
    return route.fulfill({json: {status: "queued"}});
  });
  await page.goto("/");
  await page.locator("#library-view").click();
  await page.getByRole("button", {name: "Reanalyze", exact: true}).click();
  await expect(page.getByText("Queued for reanalysis")).toBeVisible();
  expect(queued).toBe(true);
});

test.beforeEach(async ({ page }) => {
  await page.route("**/api/health", (r) =>
    r.fulfill({ json: { ok: true, openai_configured: true } }),
  );
  await page.route("**/api/chats", (r) => r.fulfill({ json: [] }));
  await page.route("**/api/contents", (r) => r.fulfill({ json: [] }));
});

test("workspace renders, suggestions compose and library opens", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "See the moment. Understand the game." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "What changed the game?" }).click();
  await expect(
    page.getByRole("textbox", { name: "Ask the analyst" }),
  ).toHaveValue(/Find the turning points/);
  await page.getByRole("button", { name: "Library" }).click();
  await expect(
    page.getByRole("heading", { name: "Start with your first source" }),
  ).toBeVisible();
  await page.locator("#library-upload").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  expect(errors).toEqual([]);
});

test("stream renders citations, safe markdown and incognito request", async ({
  page,
}) => {
  let request: any;
  const source = {
    citation: 1,
    kind: "timeline",
    text: "evidence",
    segment: {
      segment_id: "test-segment",
      content_id: "test-content",
      content_type: "document",
      source: "Тестовый протокол",
      start_time: null,
      end_time: null,
      page: 1,
      transcript: "Счет 1:1.",
      visual_description: "",
      audio_description: "",
      half: null,
      match_clock_offset: null,
      scores: [{file_time: 12, team_a: "PIT", score_a: 4, team_b: "NYI", score_b: 5, period: "OT", game_clock: null, status: "final"}],
    },
  };
  await page.route("**/api/chat", async (route) => {
    request = route.request().postDataJSON();
    const events = [
      ["chat", { id: null }],
      ["coverage", {mode: "whole_match", scanned_segments: 1, included_segments: 1, complete: true, note: "All indexed segments included."}],
      ["sources", [source]],
      [
        "delta",
        { text: '**Счет 1:1** [1]. <img src=x onerror="window.hacked=true">' },
      ],
      ["done", {}],
    ];
    await route.fulfill({
      contentType: "text/event-stream",
      body: events
        .map(
          ([kind, data]) => `event: ${kind}\ndata: ${JSON.stringify(data)}\n\n`,
        )
        .join(""),
    });
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Incognito" }).click();
  await page
    .getByRole("textbox", { name: "Ask the analyst" })
    .fill("Какой счет?");
  await page.getByRole("button", { name: "Send question" }).click();
  await expect(page.locator(".message.assistant strong")).toHaveText(
    "Счет 1:1",
  );
  expect(request.incognito).toBe(true);
  expect(request.chat_id).toBeNull();
  await expect(page.locator(".coverage-note")).toContainText("1/1 indexed segments · complete");
  await expect(page.locator(".source-type")).toContainText("TIMELINE SEGMENT");
  expect(await page.evaluate(() => (window as any).hacked)).toBeUndefined();
  await page.locator(".message.assistant a").click();
  await expect(
    page.getByRole("link", { name: "Download document" }),
  ).toBeVisible();
  await expect(page.getByText("PIT 4–5 NYI", {exact: false})).toBeVisible();
});

test("mobile has no horizontal overflow and navigation works", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.getByRole("button", { name: "Open menu" }).click();
  await page.getByRole("button", { name: "Library" }).click();
  await expect(
    page.getByRole("heading", { name: "Library", exact: true }),
  ).toBeVisible();
});

test("screenshots desktop and mobile", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".prompt-list")).toBeVisible();
  await page.screenshot({
    path: "test-results/workspace-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: "test-results/workspace-mobile.png",
    fullPage: true,
  });
});

test("theme follows the system and a manual choice survives reload", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page.locator(".prompt-list svg, .welcome img, .welcome svg")).toHaveCount(0);
  await page.screenshot({path: "test-results/workspace-dark.png", fullPage:true});
  await page.getByRole("button", {name:"Switch to light theme"}).click();
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", {name:"Switch to dark theme"}).click();
  await page.getByRole("button", {name:"Add a source", exact:true}).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.screenshot({path: "test-results/upload-dark.png", fullPage:true});
  await page.getByRole("button", {name:"Close", exact:true}).click();
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path: "test-results/workspace-dark-mobile.png", fullPage:true});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
