/* AI Recommendations: generate (AI or rule-based), save as draft, dismiss and restore. */
(function () {
  "use strict";
  const { $, esc } = window.App;
  const notice = $("#rec-notice"), genBtn = $("#rec-generate"), rulesBtn = $("#rec-rules");

  async function post(url, body) {
    try {
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
      const data = await res.json().catch(() => ({}));
      return { ok: res.ok, status: res.status, data };
    } catch (e) {
      return { ok: false, status: 0, data: { error: { kind: "network", message: "Could not reach the server. Check that it is still running." } } };
    }
  }

  const TONES = {
    info: "border-[#d9e1ff] bg-[#f3f6ff] text-[#2f4aa8]",
    ok: "border-[#c9ecdd] bg-[#effaf5] text-[#0b6b52]",
    warn: "border-[#f0dcae] bg-[#fff8e6] text-[#7a560a]",
    bad: "border-[#f1c3cb] bg-[#fff5f6] text-[#8f2a3d]",
  };
  function show(tone, html) {
    notice.className = `mt-3 rounded-xl border px-4 py-3 text-[13.5px] ${TONES[tone]}`;
    notice.innerHTML = html;
    notice.classList.remove("hidden");
    notice.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }
  const busy = (on) => { genBtn.disabled = on; rulesBtn.disabled = on; genBtn.textContent = on ? "Analyzing..." : "Generate New Recommendations"; };

  async function generate(mode, fresh) {
    busy(true);
    show("info", `<span class="typing mr-2 align-middle"><span></span><span></span><span></span></span>${mode === "ai"
      ? "Measuring your posts and campaigns, then asking the AI to choose and word the best patterns. This can take 10 to 30 seconds."
      : "Measuring your posts and campaigns and applying standard wording."}`);
    const { ok, data } = await post("/api/recommendations/generate", { mode, fresh: !!fresh });
    busy(false);

    if (ok && data.status === "created") {
      sessionStorage.setItem("toast", mode === "ai" ? (data.cached ? "Recommendations updated (AI reply reused from cache)" : "New AI recommendations generated") : "Rule-based recommendations generated");
      location.reload();
      return;
    }
    if (ok && data.status === "unchanged") {
      show("ok", `<strong>Nothing has changed.</strong> ${esc(data.message)} The recommendations below are still current.
        <button type="button" class="ml-2 font-semibold underline" data-again="${mode}" data-fresh="1">Analyse again anyway</button>`);
      return;
    }
    if (ok && data.status === "insufficient") { show("warn", esc(data.message)); return; }

    const msg = data.error ? data.error.message : "Something went wrong. Please try again.";
    show("bad", `<div class="font-semibold">No recommendations were generated.</div><div class="mt-0.5">${esc(msg)}</div>
      <div class="mt-1 text-[12.5px] opacity-80">Nothing was made up and nothing was changed.</div>
      <div class="mt-2 flex flex-wrap gap-2">
        ${mode === "ai" ? '<button type="button" class="btn btn-ghost !py-1 text-[12.5px]" data-again="ai">Try again</button>' : ""}
        ${mode === "ai" ? '<button type="button" class="btn btn-ghost !py-1 text-[12.5px]" data-again="rules">Use rule-based recommendations instead</button>' : ""}
      </div>`);
  }

  genBtn.addEventListener("click", () => generate("ai", false));
  rulesBtn.addEventListener("click", () => generate("rules", false));
  notice.addEventListener("click", (e) => {
    const b = e.target.closest("[data-again]");
    if (b) generate(b.dataset.again, b.dataset.fresh === "1");
  });

  // ---- per-recommendation actions -------------------------------------------------------
  document.addEventListener("click", async (e) => {
    const card = e.target.closest("[data-rec-id]");
    if (!card) return;
    const id = card.dataset.recId;

    if (e.target.closest("[data-save]")) {
      const btn = e.target.closest("[data-save]"), err = card.querySelector("[data-save-error]");
      btn.disabled = true; err.classList.add("hidden");
      const { ok, status, data } = await post(`/api/recommendations/${id}/save`);
      const footer = card.querySelector("[data-actions]");
      if (ok || status === 409) {
        const pid = data.post_id;
        footer.innerHTML = `<span class="text-[13.5px] font-medium text-[#0b7a5d]">Saved as a draft.</span>
          <a class="text-[13.5px] font-semibold text-signal hover:underline" href="/content/${esc(pid)}?${window.App.query()}">View draft</a>`;
        window.App.toast(ok ? "Saved to the Content Library as a draft" : "Already saved as a draft");
      } else {
        btn.disabled = false;
        const d = Array.isArray(data.detail) ? data.detail.map((x) => x.msg).join(" ") : (data.detail || "Could not save. Try again.");
        err.textContent = d; err.classList.remove("hidden");
      }
    }
    if (e.target.closest("[data-dismiss]")) {
      const { ok } = await post(`/api/recommendations/${id}/dismiss`);
      if (ok) { sessionStorage.setItem("toast", "Dismissed. You can restore it from the history."); location.reload(); }
      else window.App.toast("Could not dismiss this recommendation.");
    }
    if (e.target.closest("[data-restore]")) {
      const { ok } = await post(`/api/recommendations/${id}/restore`);
      if (ok) { sessionStorage.setItem("toast", "Restored"); location.reload(); }
      else window.App.toast("Could not restore this recommendation.");
    }
  });
})();
