import {
  createIcons,
  ScanLine,
  Plus,
  MessagesSquare,
  FolderOpen,
  Radar,
  KeyRound,
  Menu,
  VenetianMask,
  AudioLines,
  ArrowUpRight,
  Layers,
  Paperclip,
  ArrowUp,
  PanelRight,
  ScanEye,
  Video,
  TextSearch,
  History,
  Quote,
  X,
  UploadCloud,
  ArrowRight,
  Files,
  FileText,
  Download,
  MessageSquare,
  Trash2,
  FileStack,
  FolderPlus,
  Square,
  Sun,
  Moon,
} from "lucide";
import { marked } from "marked";
import DOMPurify from "dompurify";
import "./style.css";

type Segment = {
  segment_id: string;
  content_id: string;
  content_type: string;
  source: string;
  start_time: number | null;
  end_time: number | null;
  transcript: string;
  visual_description: string;
  audio_description: string;
  match_id: string | null;
  half: string | null;
  match_clock_offset: number | null;
  page: number | null;
  source_url: string | null;
  teams: string[];
  frame_times?: number[];
  scores?: {file_time: number; team_a: string; score_a: number; team_b: string; score_b: number; period: string | null; game_clock: string | null; status: string}[];
  events?: {file_time: number; event_type: string; description: string; certainty: string; is_replay: boolean | null}[];
};
type Source = {
  citation: number;
  segment: Segment;
  kind: string;
  text: string;
};
type Coverage = {mode: string; scanned_segments: number; included_segments: number; complete: boolean; note: string};
type Message = {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
  coverage?: Coverage;
};
type Content = {
  id: string;
  name: string;
  status: string;
  progress: string;
  error?: string;
  segments: number;
};
const state = {
  chatId: null as string | null,
  incognito: false,
  busy: false,
  messages: [] as Message[],
  sources: [] as Source[],
  contents: [] as Content[],
  selected: new Set<string>(),
  controller: null as AbortController | null,
  view: "chat",
};
const $ = <T extends HTMLElement = HTMLElement>(selector: string) =>
  document.querySelector<T>(selector)!;
const esc = (text: unknown) =>
  String(text ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
const icon = (name: string, cls = "") =>
  `<i data-lucide="${name}" class="${cls}"></i>`;
const refreshIcons = () =>
  createIcons({
    icons: {
      ScanLine,
      Plus,
      MessagesSquare,
      FolderOpen,
      Radar,
      KeyRound,
      Menu,
      VenetianMask,
      AudioLines,
      ArrowUpRight,
      Layers,
      Paperclip,
      ArrowUp,
      PanelRight,
      ScanEye,
      Video,
      TextSearch,
      History,
      Quote,
      X,
      UploadCloud,
      ArrowRight,
      Files,
      FileText,
      Download,
      MessageSquare,
      Trash2,
      FileStack,
      FolderPlus,
      Square,
      Sun,
      Moon,
    },
    attrs: { "stroke-width": 1.6 },
  });
const clock = (seconds: number | null) =>
  seconds === null
    ? "Document"
    : `${Math.floor(seconds / 60)
        .toString()
        .padStart(2, "0")}:${Math.floor(seconds % 60)
        .toString()
        .padStart(2, "0")}`;

$("#app").innerHTML = `
<aside class="sidebar" id="sidebar">
  <a class="brand" href="/" aria-label="Touchline, home"><span class="brand-mark">${icon("scan-line")}</span>touchline<span class="brand-dot">.</span></a>
  <div class="workspace-label">THE ANALYST WORKSPACE</div>
  <button class="new-chat" id="new-chat">${icon("plus")} New analysis <span>↗</span></button>
  <nav><button class="nav-item active" id="chat-view">${icon("messages-square")} Chats</button>
  <button class="nav-item" id="library-view">${icon("folder-open")} Library <span id="content-count">0</span></button></nav>
  <div class="sidebar-heading">RECENT ANALYSES</div><div id="history" class="history"><p class="empty-small">Your conversations will appear here</p></div>
  <div class="sidebar-bottom"><div class="workspace-badge">${icon("radar")}<div>Your workspace<small>Sources and history on this server</small></div></div>
  <button class="quiet-button" id="access-button">${icon("key-round")} Access token</button></div>
</aside>
<main class="main">
 <header class="topbar"><div class="topbar-title"><button class="icon-button mobile-menu" id="menu" aria-label="Open menu">${icon("menu")}</button><span>Analysis studio</span><span class="slash">/</span><strong id="view-title">New analysis</strong></div>
 <div class="topbar-actions"><button id="theme-toggle" class="theme-button" type="button" aria-label="Switch to dark theme"></button><button id="incognito" class="incognito" aria-pressed="false">${icon("venetian-mask")}<span>Incognito</span><span class="toggle"></span></button></div></header>
 <div class="workspace-body"><section class="chat-pane">
  <div id="config-note" class="config-note" hidden></div>
  <div id="conversation" class="conversation">
   <div class="welcome" id="welcome"><div class="eyebrow"><span></span> WATCH CLOSER. UNDERSTAND MORE.</div>
   <h1>See the moment.<br>Understand <em>the game.</em></h1>
   <p class="intro">Bring your footage, interviews and match notes together.<br class="desktop-br"> Ask a better question. Find the evidence behind the answer.</p>
   <div class="prompt-list" aria-label="Suggested questions">
    <button data-query="Find the turning points in this match and explain what changed.">What changed the game?</button>
    <button data-query="Analyze how the team creates and uses space, with evidence from the match.">How did the team create space?</button>
    <button data-query="Compare the match footage with the post-match analysis. Where do they agree or differ?">Does the footage tell the same story?</button>
   </div></div><div id="messages" class="messages"></div>
  </div>
  <section id="library" class="library" hidden><div class="library-title"><div class="eyebrow">YOUR KNOWLEDGE BASE</div><h1>Library</h1><p>Choose the sources for your next analysis.</p></div><div id="library-list"></div></section>
  <div class="composer-area"><div id="scope" class="scope">${icon("layers")} All ready sources</div>
   <form id="composer" class="composer"><label class="sr-only" for="query">Ask the analyst</label><textarea id="query" placeholder="What would you like to explore?" rows="1" maxlength="2000"></textarea>
   <div class="composer-controls"><button type="button" id="upload" class="attach">${icon("paperclip")}<span>Add a source</span></button><span class="composer-hint">Video, audio, documents</span><button id="send" class="send" aria-label="Send question">${icon("arrow-up")}</button></div></form>
   <p id="privacy-note" class="privacy-note">Answers use your sources. Always review the analyst’s conclusions.</p></div>
 </section>
 <aside class="evidence-pane"><div class="evidence-heading"><div>${icon("panel-right")}<strong>Analysis context</strong></div><span id="source-count">0</span></div>
 <div id="evidence"><div class="evidence-empty"><div class="evidence-symbol">${icon("scan-eye")}</div><h3>The evidence behind the game</h3><p>Clips and documents supporting<br>your answer will appear here.</p><div class="evidence-steps"><span>${icon("video")} The moment on video</span><span>${icon("text-search")} Related sources</span><span>${icon("history")} Before and after the event</span></div></div></div>
 <div class="evidence-footer">${icon("quote")} Evidence first. Conclusions second.</div></aside></div>
</main>
<dialog id="upload-modal"><form id="upload-form"><div class="dialog-heading"><h2>Add a source</h2><button type="button" class="icon-button" data-close aria-label="Close">${icon("x")}</button></div>
 <p>Upload match footage, an interview or a document.<br>Processing continues in the background.</p>
 <label class="dropzone">${icon("upload-cloud")}<strong>Choose a file</strong><span>MP4, MP3, PDF, DOCX, TXT and more · up to 1 GB</span><input type="file" id="file" required></label>
 <div class="form-grid"><label>Match / identifier<input id="match" placeholder="For example, madrid-barcelona-2026"></label><label>Teams, comma-separated<input id="teams" placeholder="Real Madrid, Barcelona"></label><label>Competition<input id="competition" placeholder="La Liga"></label><label>Half<input id="half" placeholder="Second half"></label><label>Players, comma-separated<input id="players" placeholder="Mbappé, Mbappe"></label><label>Match clock offset, seconds<input id="offset" type="number" placeholder="Leave blank if unknown"></label></div>
 <p class="small-note">Incognito keeps your conversation out of history. Uploaded sources still join the shared library.</p><div id="upload-error" role="alert"></div><button class="primary" id="upload-submit">Upload and process ${icon("arrow-right")}</button></form></dialog>
<dialog id="access-modal"><form id="access-form"><div class="dialog-heading"><h2>Workspace access</h2><button type="button" class="icon-button" data-close aria-label="Close">${icon("x")}</button></div><p>Enter the APP_TOKEN set by the server owner.</p><label>Token<input id="token" type="password" required autocomplete="current-password"></label><p id="access-error" role="alert"></p><button class="primary">Sign in</button></form></dialog>
<div id="toast" class="toast" role="status" hidden></div>`;

function toast(text: string) {
  $("#toast").textContent = text;
  $("#toast").hidden = false;
  setTimeout(() => ($("#toast").hidden = true), 6000);
}
async function api(path: string, options: RequestInit = {}) {
  const response = await fetch(`/api${path}`, options);
  if (response.status === 401) {
    $<HTMLDialogElement>("#access-modal").showModal();
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : `Server error (${response.status})`,
    );
  }
  return response;
}
function showView(view: string) {
  state.view = view;
  $("#library").hidden = view !== "library";
  $("#conversation").hidden = view === "library";
  $("#chat-view").classList.toggle("active", view === "chat");
  $("#library-view").classList.toggle("active", view === "library");
  $("#view-title").textContent =
    view === "library"
      ? "Library"
      : state.chatId
        ? "Match analysis"
        : "New analysis";
  $("#sidebar").classList.remove("mobile-open");
}
function renderMessages() {
  $("#welcome").hidden = state.messages.length > 0;
  $("#messages").innerHTML = state.messages
    .map(
      (m, i) =>
        `<article class="message ${m.role}"><div class="message-label">${m.role === "user" ? "YOU" : `${icon("scan-line")} TOUCHLINE`}</div>${m.coverage ? `<p class="coverage-note" title="${esc(m.coverage.note)}">${m.coverage.mode === "whole_match" ? `Video coverage · ${m.coverage.included_segments}/${m.coverage.scanned_segments} indexed segments${m.coverage.complete ? " · complete" : " · partial"}` : "Selected excerpts · partial video coverage"}</p>` : ""}<div class="message-body">${m.role === "user" ? esc(m.content).replace(/\n/g, "<br>") : markdown(m.content)}</div>${m.sources?.length ? `<button class="source-reopen" data-message="${i}">${icon("files")} Sources · ${m.sources.length}</button>` : ""}</article>`,
    )
    .join("");
  refreshIcons();
  $("#messages")
    .querySelectorAll<HTMLButtonElement>("[data-message]")
    .forEach(
      (b) =>
        (b.onclick = () =>
          renderSources(
            state.messages[Number(b.dataset.message)].sources || [],
          )),
    );
  $("#messages")
    .querySelectorAll<HTMLAnchorElement>('a[href^="#citation-"]')
    .forEach(
      (a) =>
        (a.onclick = (e) => {
          e.preventDefault();
          const article = a.closest("article")!;
          const index = [...$("#messages").children].indexOf(article);
          const sources = state.messages[index].sources || state.sources;
          renderSources(sources);
          const source = sources.find(
            (s) => s.citation === Number(a.hash.replace("#citation-", "")),
          );
          if (source) void openSource(source).catch((e) => toast(e.message));
        }),
    );
}
function markdown(text: string) {
  const parsed = marked.parse(
    text.replace(/\[(\d+)\](?!\()/g, "[$1](#citation-$1)"),
    { async: false },
  ) as string;
  return DOMPurify.sanitize(parsed, {
    FORBID_TAGS: ["img", "video", "audio", "iframe"],
    FORBID_ATTR: ["style"],
  });
}
function renderSources(sources: Source[]) {
  state.sources = sources;
  $("#source-count").textContent = String(sources.length);
  $(".evidence-pane").classList.toggle("has-sources", sources.length > 0);
  if (!sources.length) {
    $("#evidence").innerHTML =
      '<div class="evidence-empty"><h3>No supporting sources yet</h3><p>Add a source or refine your question.</p></div>';
    return;
  }
  $("#evidence").innerHTML =
    `<div id="player-panel"></div><div class="source-list">${sources.map((s) => `<button class="source-card" data-citation="${s.citation}"><span class="source-type">${icon(s.segment.content_type === "video" ? "video" : s.segment.content_type === "audio" ? "audio-lines" : "file-text")} ${s.kind === "timeline" ? "TIMELINE SEGMENT" : s.kind === "neighbor" ? "NEARBY SEGMENT" : "SOURCE"} <b>[${s.citation}]</b></span><strong>${esc(s.segment.match_id || s.segment.source)}</strong><span class="source-clock">${s.segment.start_time === null ? `Excerpt · page ${s.segment.page || 1}` : `${clock(s.segment.start_time)} — ${clock(s.segment.end_time)} · file time`}</span><p>${esc((s.segment.visual_description || s.segment.transcript || s.segment.audio_description).slice(0, 170))}</p><span class="source-open">Open ${icon("arrow-up-right")}</span></button>`).join("")}</div>`;
  refreshIcons();
  $("#evidence")
    .querySelectorAll<HTMLButtonElement>("[data-citation]")
    .forEach(
      (b) =>
        (b.onclick = () => {
          const source = sources.find(
            (s) => s.citation === Number(b.dataset.citation),
          );
          if (source) void openSource(source).catch((e) => toast(e.message));
        }),
    );
}
async function openSource(source: Source) {
  const s = source.segment;
  $(".evidence-pane").classList.add("has-sources");
  const url = `/api/contents/${encodeURIComponent(s.content_id)}/file`;
  const media = s.content_type === "video" ? "video" : "audio";
  const playbackStart = s.frame_times?.length ? Math.min(s.start_time ?? 0, ...s.frame_times) : (s.start_time ?? 0);
  $("#player-panel").innerHTML =
    `<div class="player-panel"><div class="mini-label">SOURCE [${source.citation}]</div><h3>${esc(s.source)}</h3>${s.start_time !== null ? `<${media} id="player" controls preload="metadata" src="${url}#t=${playbackStart}"></${media}><div class="player-timing">${esc(s.half || "")} · ${clock(s.start_time)} file time${s.match_clock_offset !== null ? ` · ${clock(s.start_time + s.match_clock_offset)} match time` : ""}</div><div class="player-actions"><button id="before">− 30 sec.</button><button id="matched">Segment</button><button id="after">+ 30 sec.</button></div>` : `<a class="source-download" href="${url}" target="_blank" rel="noopener">Download document ${icon("download")}</a>`}<details open><summary>Evidence</summary><p>${esc([s.transcript, s.visual_description, s.audio_description].filter(Boolean).join("\n\n")).replace(/\n/g, "<br>")}</p></details>${s.scores?.length ? `<details open><summary>Scoreboard observations</summary>${s.scores.map(o => `<p>${clock(o.file_time)} file time · ${esc(o.team_a)} ${o.score_a}–${o.score_b} ${esc(o.team_b)}<br>${esc([o.period, o.game_clock, o.status].filter(Boolean).join(" · "))}</p>`).join("")}</details>` : ""}${s.events?.length ? `<details><summary>Observed events</summary>${s.events.map(o => `<p>${clock(o.file_time)} · ${esc(o.event_type)} · ${esc(o.certainty)}${o.is_replay ? " · replay" : ""}<br>${esc(o.description)}</p>`).join("")}</details>` : ""}${s.frame_times?.length ? `<p class="small-note">${s.frame_times.length} sampled frames · includes boundary context</p>` : ""}<button id="neighbors-button" class="quiet-button">${icon("history")} Show nearby segments</button><div id="neighbors-list"></div></div>`;
  if (s.start_time !== null) {
    const player = $<HTMLMediaElement>("#player");
    const start = playbackStart;
    player.addEventListener(
      "loadedmetadata",
      () => (player.currentTime = start),
      { once: true },
    );
    $("#before").onclick = () => {
      player.currentTime = Math.max(0, start - 30);
    };
    $("#matched").onclick = () => {
      player.currentTime = start;
    };
    $("#after").onclick = () => {
      player.currentTime = Math.min(player.duration || start + 30, start + 30);
    };
  }
  $("#neighbors-button").onclick = async () => {
    try {
      const near: Segment[] = await (
        await api(`/segments/${s.segment_id}/neighbors?seconds=30`)
      ).json();
      $("#neighbors-list").innerHTML = near
        .map(
          (n, i) =>
            `<button class="neighbor-item" data-neighbor="${i}"><b>${clock(n.start_time)}</b><span>${esc((n.visual_description || n.transcript || n.audio_description).slice(0, 120))}</span></button>`,
        )
        .join("");
      $("#neighbors-list")
        .querySelectorAll<HTMLButtonElement>("button")
        .forEach(
          (b) =>
            (b.onclick = () =>
              void openSource({
                ...source,
                segment: near[Number(b.dataset.neighbor)],
              })),
        );
    } catch (e) {
      toast((e as Error).message);
    }
  };
  refreshIcons();
  $("#player-panel").scrollIntoView({ block: "nearest", behavior: "smooth" });
}
async function loadHistory() {
  const chats: { id: string; title: string }[] = await (
    await api("/chats")
  ).json();
  $("#history").innerHTML = chats.length
    ? chats
        .map(
          (c) =>
            `<div class="history-row"><button data-chat="${esc(c.id)}">${icon("message-square")}<span>${esc(c.title)}</span></button><button data-delete="${esc(c.id)}" class="delete-chat" aria-label="Delete chat">${icon("trash-2")}</button></div>`,
        )
        .join("")
    : '<p class="empty-small">Your conversations will appear here</p>';
  $("#history")
    .querySelectorAll<HTMLButtonElement>("[data-chat]")
    .forEach(
      (b) =>
        (b.onclick = async () => {
          if (state.busy) return;
          try {
            state.messages = await (
              await api(`/chats/${b.dataset.chat}`)
            ).json();
            state.chatId = b.dataset.chat!;
            state.incognito = false;
            updatePrivacy();
            showView("chat");
            renderMessages();
            renderSources(
              [...state.messages].reverse().find((m) => m.sources?.length)
                ?.sources || [],
            );
          } catch (e) {
            toast((e as Error).message);
          }
        }),
    );
  $("#history")
    .querySelectorAll<HTMLButtonElement>("[data-delete]")
    .forEach(
      (b) =>
        (b.onclick = async () => {
          if (state.busy) return;
          try {
            await api(`/chats/${b.dataset.delete}`, { method: "DELETE" });
            if (state.chatId === b.dataset.delete) newChat();
            await loadHistory();
          } catch (e) {
            toast((e as Error).message);
          }
        }),
    );
  refreshIcons();
}
async function loadContents() {
  state.contents = await (await api("/contents")).json();
  $("#content-count").textContent = String(state.contents.length);
  $("#library-list").innerHTML = state.contents.length
    ? state.contents
        .map(
          (c) =>
            `<article class="material"><input type="checkbox" aria-label="Select ${esc(c.name)}" data-select="${c.id}" ${state.selected.has(c.id) ? "checked" : ""} ${c.status !== "ready" ? "disabled" : ""}>${icon("file-stack")}<div><h3>${esc(c.name)}</h3><p>${esc(c.progress)}${c.status === "ready" ? ` · ${c.segments} segments` : ""}</p>${c.error ? `<p class="error-text">${esc(c.error)}</p>` : ""}</div><span class="status ${c.status}">${({ ready: "Ready", queued: "Queued", running: "Processing", failed: "Error" } as Record<string, string>)[c.status]}</span>${c.status === "failed" ? `<button class="quiet-button" data-retry="${c.id}">Retry</button>` : c.status === "ready" ? `<button class="quiet-button" data-reindex="${c.id}" title="Reprocess with the current video analysis settings">Reanalyze</button>` : ""}</article>`,
        )
        .join("")
    : '<div class="library-empty">' +
      icon("folder-plus") +
      '<h2>Start with your first source</h2><p>Add match footage, an interview or an analysis document.</p><button class="primary" id="library-upload">Add a source</button></div>';
  $("#library-list")
    .querySelectorAll<HTMLInputElement>("[data-select]")
    .forEach(
      (el) =>
        (el.onchange = () => {
          el.checked
            ? state.selected.add(el.dataset.select!)
            : state.selected.delete(el.dataset.select!);
          updateScope();
        }),
    );
  $("#library-list")
    .querySelectorAll<HTMLButtonElement>("[data-retry], [data-reindex]")
    .forEach(
      (el) =>
        (el.onclick = async () => {
          try {
            await api(`/contents/${el.dataset.retry || el.dataset.reindex}/${el.dataset.reindex ? "reindex" : "retry"}`, {
              method: "POST",
            });
            await loadContents();
          } catch (e) {
            toast((e as Error).message);
          }
        }),
    );
  if (document.querySelector("#library-upload"))
    $("#library-upload").onclick = () =>
      $<HTMLDialogElement>("#upload-modal").showModal();
  refreshIcons();
}
function updateScope() {
  $("#scope").innerHTML =
    `${icon("layers")} ${state.selected.size ? `Selected sources: ${state.selected.size}` : "All ready sources"}`;
  refreshIcons();
}
function updatePrivacy() {
  $("#incognito").setAttribute("aria-pressed", String(state.incognito));
  $("#privacy-note").textContent = state.incognito
    ? "Incognito: this conversation is not saved on the app server. Data is sent to OpenAI for processing."
    : "Answers use your sources. Always review the analyst’s conclusions.";
}
function newChat() {
  if (state.busy) return;
  state.chatId = null;
  state.messages = [];
  renderMessages();
  renderSources([]);
  showView("chat");
  $<HTMLTextAreaElement>("#query").focus();
}
$("#new-chat").onclick = newChat;
$("#chat-view").onclick = () => showView("chat");
$("#library-view").onclick = () => showView("library");
$("#menu").onclick = () => $("#sidebar").classList.toggle("mobile-open");
$("#incognito").onclick = () => {
  if (state.busy) return;
  state.incognito = !state.incognito;
  newChat();
  updatePrivacy();
};
$("#upload").onclick = () => $<HTMLDialogElement>("#upload-modal").showModal();
$("#access-button").onclick = () =>
  $<HTMLDialogElement>("#access-modal").showModal();
document
  .querySelectorAll<HTMLButtonElement>("[data-close]")
  .forEach((b) => (b.onclick = () => b.closest("dialog")!.close()));
document.querySelectorAll<HTMLButtonElement>("[data-query]").forEach(
  (b) =>
    (b.onclick = () => {
      $<HTMLTextAreaElement>("#query").value = b.dataset.query!;
      $<HTMLTextAreaElement>("#query").focus();
    }),
);
$("#query").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    $<HTMLFormElement>("#composer").requestSubmit();
  }
});
$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (state.busy) {
    state.controller?.abort();
    return;
  }
  const input = $<HTMLTextAreaElement>("#query");
  const query = input.value.trim();
  if (!query) return;
  const history = state.messages
    .slice(-12)
    .map(({ role, content }) => ({ role, content }));
  state.busy = true;
  state.controller = new AbortController();
  showView("chat");
  state.messages.push(
    { role: "user", content: query },
    { role: "assistant", content: "" },
  );
  const answer = state.messages.at(-1)!;
  input.value = "";
  $("#send").innerHTML = icon("square");
  $("#send").setAttribute("aria-label", "Stop response");
  renderMessages();
  try {
    const response = await api("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: state.controller.signal,
      body: JSON.stringify({
        query,
        chat_id: state.chatId,
        incognito: state.incognito,
        history,
        content_ids: [...state.selected],
      }),
    });
    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let doneEvent = false;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop()!;
      for (const block of blocks) {
        const kind = block.match(/^event: (.+)$/m)?.[1];
        const raw = block.match(/^data: (.+)$/m)?.[1];
        if (!raw) continue;
        const data = JSON.parse(raw);
        if (kind === "chat" && !state.incognito) state.chatId = data.id;
        if (kind === "status") $("#scope").textContent = data.text;
        if (kind === "coverage") {
          answer.coverage = data;
          renderMessages();
        }
        if (kind === "sources") {
          answer.sources = data;
          renderSources(data);
        }
        if (kind === "delta") {
          answer.content += data.text;
          renderMessages();
          $("#conversation").scrollTop = $("#conversation").scrollHeight;
        }
        if (kind === "error") throw new Error(data.message);
        if (kind === "done") doneEvent = true;
      }
    }
    if (!doneEvent)
      throw new Error("Connection interrupted. The answer may be incomplete.");
  } catch (e) {
    const error = e as Error;
    const message =
      error.name === "AbortError"
        ? "Generation stopped. The unfinished answer was not saved."
        : error.message;
    toast(message);
    answer.content += `\n\n> ${message}`;
    renderMessages();
  } finally {
    state.busy = false;
    state.controller = null;
    $("#send").innerHTML = icon("arrow-up");
    $("#send").setAttribute("aria-label", "Send question");
    updateScope();
    void loadHistory().catch(() => {});
  }
});
$("#upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = $<HTMLInputElement>("#file").files?.[0];
  if (!file) return;
  const val = (id: string) => $<HTMLInputElement>(id).value.trim();
  const form = new FormData();
  form.append("file", file);
  form.append(
    "metadata",
    JSON.stringify({
      match_id: val("#match") || null,
      teams: val("#teams")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      players: val("#players")
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      competition: val("#competition") || null,
      half: val("#half") || null,
      match_clock_offset: val("#offset") ? Number(val("#offset")) : null,
    }),
  );
  const button = $<HTMLButtonElement>("#upload-submit");
  button.disabled = true;
  button.textContent = "Uploading…";
  $("#upload-error").textContent = "";
  try {
    await api("/contents", { method: "POST", body: form });
    $<HTMLDialogElement>("#upload-modal").close();
    $<HTMLFormElement>("#upload-form").reset();
    await loadContents();
    showView("library");
    toast("Source uploaded. Processing continues in the background.");
  } catch (e) {
    $("#upload-error").textContent = (e as Error).message;
  } finally {
    button.disabled = false;
    button.textContent = "Upload and process";
  }
});
$("#access-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: $<HTMLInputElement>("#token").value }),
    });
    $<HTMLDialogElement>("#access-modal").close();
    $<HTMLInputElement>("#token").value = "";
    await initialize();
  } catch (e) {
    $("#access-error").textContent = (e as Error).message;
  }
});
async function initialize() {
  try {
    const health = await (await api("/health")).json();
    $("#config-note").hidden = health.openai_configured;
    $("#config-note").textContent =
      "Add OPENAI_API_KEY to .env and restart the server to start analyzing your sources.";
    await Promise.all([loadHistory(), loadContents()]);
  } catch (e) {
    $("#config-note").hidden = false;
    $("#config-note").textContent = (e as Error).message;
  }
}
const themeQuery = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme(theme: "light" | "dark") {
  document.documentElement.dataset.theme = theme;
  const dark = theme === "dark";
  $("#theme-toggle").innerHTML = icon(dark ? "sun" : "moon");
  $("#theme-toggle").setAttribute(
    "aria-label",
    dark ? "Switch to light theme" : "Switch to dark theme",
  );
  $("#theme-toggle").setAttribute("aria-pressed", String(dark));
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", dark ? "#111922" : "#f5f7fb");
  refreshIcons();
}
function savedTheme() {
  try {
    return localStorage.getItem("touchline-theme");
  } catch {
    return null;
  }
}
applyTheme(
  savedTheme() === "dark" || (savedTheme() !== "light" && themeQuery.matches)
    ? "dark"
    : "light",
);
$("#theme-toggle").onclick = () => {
  const theme =
    document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  try {
    localStorage.setItem("touchline-theme", theme);
  } catch {
    /* Use session-only theme. */
  }
  applyTheme(theme);
};
themeQuery.addEventListener("change", (event) => {
  if (!savedTheme()) applyTheme(event.matches ? "dark" : "light");
});
void initialize();
setInterval(() => {
  if (state.contents.some((c) => ["queued", "running"].includes(c.status)))
    void loadContents().catch(() => {});
}, 3000);
