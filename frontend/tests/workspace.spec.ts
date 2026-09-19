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
  await page.route("**/api/contents", r => r.fulfill({json:[{id:"test-content",name:"Match.pdf",status:"ready",progress:"Ready",segments:1}]}));
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
  await expect(page.locator("#incognito")).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator("#privacy-note")).toContainText("This chat stays out of history");
  expect(request.chat_id).toBeNull();
  await expect(page.locator(".coverage-note")).toContainText("1/1 indexed segments · complete");
  await expect(page.locator(".source-type")).toContainText("TIMELINE SEGMENT");
  expect(await page.evaluate(() => (window as any).hacked)).toBeUndefined();
  await page.locator(".message.assistant a").click();
  await expect(
    page.getByRole("link", { name: "Download document" }),
  ).toBeVisible();
  await expect(page.getByText("PIT 4–5 NYI", {exact: false})).toBeVisible();
  await page.screenshot({path: "test-results/analysis-evidence.png", fullPage: true});
});

test("upload retains every metadata field and library selection", async ({ page }) => {
  let uploaded = false;
  let uploadBody = "";
  await page.route("**/api/contents", async route => {
    if (route.request().method() === "POST") {
      uploaded = true;
      uploadBody = route.request().postDataBuffer()!.toString("utf8");
      return route.fulfill({json: {id: "match-notes"}});
    }
    return route.fulfill({json: uploaded ? [{id: "match-notes", name: "Match notes.txt", status: "ready", progress: "Ready", segments: 8}] : []});
  });
  await page.goto("/");
  await page.getByRole("button", {name: "Add a source", exact: true}).click();
  await page.locator("#file").setInputFiles({name: "Match notes.txt", mimeType: "text/plain", buffer: Buffer.from("Final whistle. Home team wins.")});
  await page.getByLabel("Match / identifier").fill("match-2026");
  await page.getByLabel("Teams, comma-separated").fill("Penguins, Islanders");
  await page.getByLabel("Competition", {exact: true}).fill("NHL");
  await page.getByLabel("Half", {exact: true}).fill("OT");
  await page.getByLabel("Players, comma-separated").fill("Barzal, Crosby");
  await page.getByLabel("Match clock offset, seconds").fill("60");
  await page.getByRole("button", {name: "Upload and process"}).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.getByRole("heading", {name: "Match notes.txt"})).toBeVisible();
  expect(uploadBody).toContain(JSON.stringify({match_id:"match-2026", teams:["Penguins","Islanders"], players:["Barzal","Crosby"], competition:"NHL", half:"OT", match_clock_offset:60}));
  expect(uploadBody).toContain("Final whistle. Home team wins.");
  await page.getByRole("checkbox", {name: "Select Match notes.txt"}).check();
  await expect(page.locator("#scope")).toHaveText("Selected sources: 1");
  await page.getByRole("button", {name: "Switch to dark theme"}).click();
  await page.screenshot({path: "test-results/library-dark.png", fullPage: true});
  await page.getByRole("button", {name: "Incognito"}).click();
  await expect(page.locator("#scope")).toHaveText("Selected sources: 1");
  await expect(page.locator("#privacy-note")).toContainText("Sources stay in your library");
});

test("narrow-screen navigation closes with Escape and backdrop", async ({ page }) => {
  await page.setViewportSize({width: 320, height: 740});
  await page.goto("/");
  await page.getByRole("button", {name: "Open menu"}).click();
  await expect(page.getByRole("button", {name: "New analysis"})).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("button", {name: "Open menu"})).toBeFocused();
  await expect(page.locator("#sidebar")).not.toBeVisible();
  await page.getByRole("button", {name: "Open menu"}).click();
  await page.locator("#nav-scrim").click({position: {x: 300, y: 200}});
  await expect(page.locator("#sidebar")).not.toBeVisible();
  await page.getByRole("button", {name: "Incognito"}).click();
  await expect(page.locator("#incognito")).toHaveAttribute("aria-pressed", "true");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({path: "test-results/incognito-mobile.png", fullPage: true});
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

test("deleting a source requires confirmation, handles errors and clears selection", async ({page}) => {
  let deleted = false;
  let attempts = 0;
  await page.route("**/api/contents", route => route.fulfill({json: deleted ? [] : [{
    id: "delete-test", name: "Highlights.mp4", status: "ready", progress: "Ready", segments: 116,
  }]}));
  await page.route("**/api/contents/delete-test", route => {
    expect(route.request().method()).toBe("DELETE");
    attempts++;
    if (attempts === 1) return route.fulfill({status: 503, json: {detail: "Deletion could not finish. Please retry."}});
    deleted = true;
    return route.fulfill({status: 204});
  });
  await page.goto("/");
  await page.locator("#library-view").click();
  await page.getByRole("checkbox", {name: "Select Highlights.mp4"}).check();
  await page.getByRole("button", {name: "Delete Highlights.mp4"}).click();
  await expect(page.getByRole("dialog", {name: "Delete source?"})).toBeVisible();
  await page.getByRole("button", {name: "Cancel", exact: true}).click();
  expect(attempts).toBe(0);
  await page.getByRole("button", {name: "Delete Highlights.mp4"}).click();
  await page.getByRole("button", {name: "Delete permanently"}).click();
  await expect(page.getByRole("alert")).toContainText("Deletion could not finish");
  await expect(page.getByRole("button", {name: "Delete permanently"})).toBeEnabled();
  await page.screenshot({path: "test-results/delete-source.png", animations: "disabled"});
  await page.getByRole("button", {name: "Delete permanently"}).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.getByRole("heading", {name: "Start with your first source"})).toBeVisible();
  await expect(page.locator("#scope")).toHaveText("Select a source");
  await expect(page.locator("#content-count")).toHaveText("0");
});

test("empty workspace fits the viewport and the composer grows only for extra lines", async ({page}) => {
  await page.route("**/api/contents", r => r.fulfill({json:[{id:"test-content",name:"Match.pdf",status:"ready",progress:"Ready",segments:1}]}));
  await page.goto("/");
  for (const viewport of [{width:1440,height:900}, {width:1280,height:640}, {width:1024,height:600}, {width:390,height:844}, {width:320,height:740}]) {
    await page.setViewportSize(viewport);
    const layout = await page.evaluate(() => {
      const conversation = document.querySelector("#conversation")!;
      const composer = document.querySelector("#composer")!;
      const prompts = document.querySelector(".prompt-list")!;
      return {
        scrolls: conversation.scrollHeight > conversation.clientHeight + 1,
        composerHeight: composer.getBoundingClientRect().height,
        bottom: document.querySelector("#privacy-note")!.getBoundingClientRect().bottom,
        overlapping: prompts.getBoundingClientRect().bottom > composer.getBoundingClientRect().top,
      };
    });
    expect(layout, JSON.stringify(viewport)).toMatchObject({scrolls:false, overlapping:false});
    expect(layout.composerHeight).toBeLessThan(65);
    expect(layout.bottom).toBeLessThanOrEqual(viewport.height);
  }
  await page.setViewportSize({width:1280,height:640});
  await page.screenshot({path:"test-results/compact-start.png", animations:"disabled"});
  const input = page.getByRole("textbox", {name: "Ask the analyst"});
  await input.fill("First line\nSecond line\nThird line");
  expect((await input.boundingBox())!.height).toBeGreaterThan(24);
  await input.fill("Short question");
  expect((await input.boundingBox())!.height).toBe(24);
  await page.route("**/api/chat", route => route.fulfill({contentType:"text/event-stream", body:
    `event: delta\ndata: ${JSON.stringify({text: "A detailed match analysis.\n\n".repeat(100)})}\n\nevent: done\ndata: {}\n\n`
  }));
  await page.getByRole("button", {name: "Send question"}).click();
  await expect(page.locator(".message.assistant")).toContainText("A detailed match analysis.");
  expect(await page.locator("#conversation").evaluate(el => getComputedStyle(el).overflowY)).toBe("auto");
  expect(await page.locator("#conversation").evaluate(el => el.scrollHeight > el.clientHeight)).toBe(true);
});

test("missing Gemini key is visible without blocking the library", async ({page}) => {
  await page.route("**/api/health", route => route.fulfill({json:{
    ok:true, openai_configured:true, chat_provider:"gemini", chat_configured:false,
  }}));
  await page.goto("/");
  await expect(page.locator("#config-note")).toContainText("Gemini answers require GEMINI_API_KEY");
  await page.locator("#library-view").click();
  await expect(page.getByRole("heading", {name:"Library",exact:true})).toBeVisible();
});

test("a second upload selects only that video, persists selection and allows explicit all-sources", async ({page}) => {
  let uploaded = false;
  const requests: any[] = [];
  const first = {id:"first-video",name:"First.mp4",status:"ready",progress:"Ready",segments:116};
  const second = {id:"second-video",name:"Second.mp4",status:"ready",progress:"Ready",segments:105};
  await page.route("**/api/contents", r => {
    if (r.request().method() === "POST") { uploaded = true; return r.fulfill({json:{id:second.id}}); }
    return r.fulfill({json:uploaded ? [second,first] : [first]});
  });
  await page.route("**/api/chat", r => {
    requests.push(r.request().postDataJSON());
    return r.fulfill({contentType:"text/event-stream",body:'event: delta\ndata: {"text":"Test answer"}\n\nevent: done\ndata: {}\n\n'});
  });
  await page.goto("/");
  await expect(page.locator("#scope-name")).toHaveText("First.mp4");
  await page.getByRole("button",{name:"Add a source",exact:true}).click();
  await page.locator("#file").setInputFiles({name:"Second.mp4",mimeType:"video/mp4",buffer:Buffer.from("test")});
  await page.getByRole("button",{name:"Upload and process"}).click();
  await expect(page.locator("#scope-name")).toHaveText("Second.mp4");
  await page.reload();
  await expect(page.locator("#scope-name")).toHaveText("Second.mp4");
  await page.getByRole("textbox",{name:"Ask the analyst"}).fill("What shirt numbers scored?");
  await page.getByRole("button",{name:"Send question"}).click();
  await expect(page.locator(".message.assistant")).toContainText("Test answer");
  expect(requests[0].content_ids).toEqual(["second-video"]);
  expect(requests[0].all_sources).toBe(false);
  await page.getByRole("button",{name:"Use all sources",exact:true}).click();
  await page.getByRole("textbox",{name:"Ask the analyst"}).fill("Compare the videos");
  await page.getByRole("button",{name:"Send question"}).click();
  await expect(page.locator(".message.assistant")).toContainText("Test answer");
  expect(requests[1].all_sources).toBe(true);
  expect(requests[1].content_ids).toEqual([]);
});
