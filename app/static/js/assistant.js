/* AI Assistant: chat about the data, and generate an editable post draft. */
(function () {
  "use strict";
  const { $, esc, state } = window.App;
  const cfg = $("#assistant-config");
  const model = cfg.dataset.model;
  const campaignNames = JSON.parse(cfg.dataset.campaigns || "{}");

  // ---- tabs ------------------------------------------------------------------------
  const tabs = { ask: [$("#tab-ask"), $("#panel-ask"), "grid"], draft: [$("#tab-draft"), $("#panel-draft"), "grid"] };
  function showTab(name) {
    Object.entries(tabs).forEach(([k, [btn, panel]]) => {
      const on = k === name;
      btn.setAttribute("aria-selected", on);
      btn.classList.toggle("bg-signal", on); btn.classList.toggle("text-white", on);
      btn.classList.toggle("text-mute", !on);
      panel.classList.toggle("hidden", !on); panel.classList.toggle("grid", on);
    });
    history.replaceState(null, "", location.pathname + location.search + (name === "draft" ? "#draft" : ""));
  }
  tabs.ask[0].addEventListener("click", () => showTab("ask"));
  tabs.draft[0].addEventListener("click", () => showTab("draft"));
  showTab(location.hash === "#draft" ? "draft" : "ask");

  // ---- minimal, safe markdown (escape first, then format) -----------------------------
  const inline = (s) => s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, '<code class="rounded bg-canvas px-1">$1</code>');
  function md(src) {
    const lines = esc(src.trim()).split(/\r?\n/);
    let html = "", list = null, para = [], table = [];
    const fPara = () => { if (para.length) { html += `<p>${inline(para.join(" "))}</p>`; para = []; } };
    const fList = () => { if (list) { html += `<${list.t}>${list.items.map((i) => `<li>${inline(i)}</li>`).join("")}</${list.t}>`; list = null; } };
    const fTable = () => {
      if (!table.length) return;
      const rows = table.filter((r) => !/^\|?[\s:|-]+\|?$/.test(r)).map((r) => r.replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
      if (rows.length) {
        html += "<table><thead><tr>" + rows[0].map((c) => `<th>${inline(c)}</th>`).join("") + "</tr></thead><tbody>" +
          rows.slice(1).map((r) => "<tr>" + r.map((c) => `<td>${inline(c)}</td>`).join("") + "</tr>").join("") + "</tbody></table>";
      }
      table = [];
    };
    for (const raw of lines) {
      const line = raw.trim();
      if (!line) { fPara(); fList(); fTable(); continue; }
      if (line.startsWith("|")) { fPara(); fList(); table.push(line); continue; }
      fTable();
      const ul = line.match(/^[-*\u2022]\s+(.*)/), ol = line.match(/^\d+[.)]\s+(.*)/), h = line.match(/^#{1,6}\s+(.*)/);
      if (ul || ol) {
        fPara(); const t = ul ? "ul" : "ol";
        if (list && list.t !== t) fList();
        list = list || { t, items: [] }; list.items.push((ul || ol)[1]); continue;
      }
      fList();
      if (h) { fPara(); html += `<p><strong>${inline(h[1])}</strong></p>`; continue; }
      para.push(line);
    }
    fPara(); fList(); fTable();
    return html;
  }

  // ---- API helper: always returns {ok, data} and never throws --------------------------
  async function post(url, body) {
    try {
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, status: res.status, data };
    } catch (e) {
      return { ok: false, status: 0, data: { error: { kind: "network", message: "Could not reach the server. Check that it is still running." } } };
    }
  }
  const errText = (data) => {
    if (data.error) return data.error.message;
    if (Array.isArray(data.detail)) return data.detail.map((d) => `${d.loc[d.loc.length - 1]}: ${d.msg}`).join(" ");
    return "Something went wrong. Please try again.";
  };

  // ======================================================================================
  // Chat
  // ======================================================================================
  const log = $("#chat-log"), input = $("#chat-input"), sendBtn = $("#chat-send"), form = $("#chat-form");
  let history_ = [];          // [{role, content}] successful turns only
  let pending = false, lastQuestion = "";

  function ctxLabel() {
    const parts = [state.days === "90" ? "All 90 days" : `Last ${state.days} days`, state.platform === "all" ? "all platforms" : state.platform];
    if (state.campaign !== "all") parts.push(campaignNames[state.campaign] || state.campaign);
    return parts.join(" \u00B7 ");
  }
  const updateChip = () => { $("#ctx-chip").textContent = ctxLabel(); };
  window.App.onFilterChange = async () => { updateChip(); };     // no reload: keep the conversation
  updateChip();

  const scroll = () => { log.scrollTop = log.scrollHeight; };
  function add(html) {
    const empty = $("#chat-empty"); if (empty) empty.remove();
    const wrap = document.createElement("div"); wrap.innerHTML = html;
    const el = wrap.firstElementChild; log.appendChild(el); scroll(); return el;
  }
  const userBubble = (t) => `<div class="flex justify-end"><div class="max-w-[85%] whitespace-pre-line rounded-2xl rounded-br-md bg-signal px-4 py-2.5 text-[14px] leading-relaxed text-white">${esc(t)}</div></div>`;
  const typingBubble = () => `<div class="flex" data-typing><div class="rounded-2xl rounded-bl-md border border-line bg-white px-4 py-3"><span class="typing" aria-label="Thinking"><span></span><span></span><span></span></span></div></div>`;
  const aiBubble = (d) => `<div class="flex"><div class="max-w-[92%] rounded-2xl rounded-bl-md border border-line bg-white px-4 py-3">
      <div class="prose-chat text-[14px] leading-relaxed">${md(d.answer)}</div>
      <div class="mt-3 flex flex-wrap items-center gap-1.5 border-t border-line pt-2.5 text-[11.5px] text-mute">
        <span class="font-semibold">Data used:</span>${d.sections.map((s) => `<span class="rounded-full bg-canvas px-2 py-0.5">${esc(s.title)}</span>`).join("")}
        <span class="ml-auto">${d.cached ? "Cached \u00B7 " : ""}${esc(d.model)}</span></div></div></div>`;
  const errBubble = (msg, retry) => `<div class="flex"><div class="max-w-[92%] rounded-2xl rounded-bl-md border border-[#f1c3cb] bg-[#fff5f6] px-4 py-3 text-[13.5px] text-[#8f2a3d]" role="alert">
      <div class="font-semibold">The AI could not answer</div><div class="mt-0.5">${esc(msg)}</div>
      <div class="mt-1.5 text-[12px] text-[#a85a68]">No answer was generated. The rest of Compass is unaffected.</div>
      ${retry ? '<button type="button" data-retry class="btn btn-ghost mt-2 !py-1 text-[12.5px]">Try again</button>' : ""}</div></div>`;

  async function ask(question, { retry = false } = {}) {
    if (pending || !question.trim()) return;
    pending = true; sendBtn.disabled = true; lastQuestion = question;
    if (!retry) add(userBubble(question));
    const typing = add(typingBubble());
    const { ok, data } = await post("/api/assistant/ask", {
      question, history: history_.slice(-12), filters: { days: +state.days, platform: state.platform, campaign: state.campaign },
    });
    typing.remove();
    if (ok) {
      history_.push({ role: "user", content: question }, { role: "assistant", content: data.answer.slice(0, 1400) });
      add(aiBubble(data));
    } else {
      const el = add(errBubble(errText(data), true));
      el.querySelector("[data-retry]")?.addEventListener("click", () => { el.remove(); ask(lastQuestion, { retry: true }); });
    }
    pending = false; sendBtn.disabled = false; input.focus();
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); const q = input.value.trim(); if (!q) return; input.value = ""; autosize(); ask(q); });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); } });
  const prefill = new URLSearchParams(location.search).get("ask");
  if (prefill) { input.value = prefill.slice(0, 500); input.focus(); }   // prefilled, never auto-sent
  const autosize = () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 128) + "px"; };
  input.addEventListener("input", autosize);
  document.querySelectorAll(".suggestion").forEach((b) => b.addEventListener("click", () => ask(b.textContent.trim())));
  const emptyHtml = $("#chat-empty").outerHTML;
  $("#clear-chat").addEventListener("click", () => {
    history_ = []; log.innerHTML = emptyHtml;
    log.querySelectorAll(".suggestion").forEach((b) => b.addEventListener("click", () => ask(b.textContent.trim())));
  });

  // ======================================================================================
  // Post generator
  // ======================================================================================
  const gform = $("#gen-form");
  if (state.platform !== "all") gform.elements.platform.value = state.platform;   // follow the top-bar platform
  window.App.onFilterChange = async () => {
    updateChip();
    if (state.platform !== "all") gform.elements.platform.value = state.platform;
  };
  const el = { empty: $("#gen-empty"), loading: $("#gen-loading"), result: $("#gen-result"), text: $("#gen-text"),
               count: $("#gen-count"), when: $("#gen-when") };
  let lastReq = null;
  const strengthChip = { solid: ["chip-good", "Solid evidence"], moderate: ["chip-flat", "Moderate evidence"], thin: ["chip-bad", "Thin evidence: treat as a test"] };

  const setCount = () => { el.count.textContent = `${el.text.value.length} / 3000`; };
  el.text.addEventListener("input", setCount);

  function clearGenErrors() {
    gform.querySelectorAll("[data-error-for]").forEach((p) => { p.textContent = ""; p.classList.add("hidden"); });
    $("#gen-error").classList.add("hidden");
  }

  async function generate(fresh) {
    clearGenErrors();
    const v = (n) => gform.elements[n].value;
    const body = { topic: v("topic"), platform: v("platform"), content_type: v("content_type"), audience: v("audience"),
                   objective: v("objective"), tone: v("tone"), fresh: !!fresh };
    el.empty.classList.add("hidden"); el.result.classList.add("hidden"); el.loading.classList.remove("hidden"); el.loading.classList.add("flex");
    $("#gen-btn").disabled = true;
    const { ok, data } = await post("/api/assistant/generate", body);
    el.loading.classList.add("hidden"); el.loading.classList.remove("flex"); $("#gen-btn").disabled = false;
    if (!ok) {
      (el.result.classList.contains("hidden") ? el.empty : el.result).classList.remove("hidden");
      if (Array.isArray(data.detail)) {
        data.detail.forEach((d) => { const f = d.loc[d.loc.length - 1]; const s = gform.querySelector(`[data-error-for="${f}"]`); if (s) { s.textContent = d.msg; s.classList.remove("hidden"); } });
      } else {
        const e = $("#gen-error"); e.textContent = errText(data) + (data.error ? " No draft was generated." : ""); e.classList.remove("hidden");
      }
      return;
    }
    lastReq = body; renderResult(data);
  }

  function renderResult(d) {
    el.result.classList.remove("hidden");
    const [cls, label] = strengthChip[d.strength] || strengthChip.thin;
    const chip = $("#gen-strength"); chip.className = "chip " + cls; chip.textContent = label;
    $("#gen-cached").classList.toggle("hidden", !d.cached);
    const test = $("#gen-test");
    test.classList.toggle("hidden", !d.is_test);
    if (d.is_test) test.textContent = "Not enough history for this format on this platform to claim a trend. Publish this as a test and compare the result.";
    el.text.value = d.full_text; setCount();
    $("#gen-meta").textContent = `Hook: ${d.hook}`;
    $("#gen-align").textContent = d.alignment;
    const tone = { good: "#10a37f", bad: "#d6455d", info: "#9aa6c3" };
    $("#gen-evidence").innerHTML = d.evidence.map((e) => `<li class="flex gap-3 px-5 py-3"><span class="dot mt-[7px]" style="background:${tone[e.tone] || tone.info}"></span>
        <div><div class="font-semibold">${esc(e.label)}</div><div class="text-mute">${esc(e.value)}</div></div></li>`).join("");
    $("#gen-saved").classList.add("hidden"); $("#gen-save-error").classList.add("hidden");
    $("#gen-save").disabled = false;
    el.result.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // After a save the button stays off (no accidental duplicates) until something is edited.
  const rearm = () => { $("#gen-save").disabled = false; };
  el.text.addEventListener("input", rearm);
  el.when.addEventListener("input", rearm);

  gform.addEventListener("submit", (e) => { e.preventDefault(); generate(false); });
  $("#gen-regen").addEventListener("click", () => generate(true));

  $("#gen-save").addEventListener("click", async () => {
    if (!lastReq) return;
    const btn = $("#gen-save"); btn.disabled = true;
    $("#gen-save-error").classList.add("hidden"); $("#gen-saved").classList.add("hidden");
    el.when.parentElement.querySelector("[data-error-for]").classList.add("hidden");
    const when = el.when.value || null;
    const { ok, data } = await post("/api/assistant/save-draft", {
      platform: lastReq.platform, content_type: lastReq.content_type, topic: lastReq.topic,
      caption: el.text.value, status: when ? "proposed" : "draft", scheduled_for: when, campaign_id: null,
    });
    if (!ok) {
      btn.disabled = false;
      const d = Array.isArray(data.detail) ? data.detail : [];
      const when_ = d.find((x) => x.loc[x.loc.length - 1] === "scheduled_for");
      if (when_) { const s = el.when.parentElement.querySelector("[data-error-for]"); s.textContent = when_.msg; s.classList.remove("hidden"); }
      const rest = d.filter((x) => x !== when_).map((x) => x.msg).join(" ");
      if (rest || !d.length) { const e = $("#gen-save-error"); e.textContent = rest || errText(data); e.classList.remove("hidden"); }
      return;
    }
    const s = $("#gen-saved");
    s.innerHTML = `${data.status === "proposed" ? "Saved as a proposed post." : "Saved as a draft."} <a class="underline" href="/content/${esc(data.id)}?${window.App.query()}">View in Content Library</a>`;
    s.classList.remove("hidden");
  });
})();
