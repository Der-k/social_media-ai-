/* Content library: auto-applying filters, row links, and the create / edit / delete draft form. */
(function () {
  "use strict";
  const { $, esc } = window.App;

  // ---- library filters: apply on change, debounce search ---------------------------
  const filters = $("#library-filters");
  if (filters) {
    let timer;
    const q = $("#lib-q");
    filters.querySelectorAll("select").forEach((s) => s.addEventListener("change", () => filters.submit()));
    q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => filters.submit(), 400); });
    if (new URLSearchParams(location.search).get("q")) { q.focus(); q.setSelectionRange(q.value.length, q.value.length); }
  }

  // Whole table row opens the post (the caption link still works for keyboard users).
  document.querySelectorAll("tr[data-href]").forEach((tr) => {
    tr.addEventListener("click", (e) => { if (!e.target.closest("a")) location.href = tr.dataset.href; });
  });

  // ---- draft form ------------------------------------------------------------------
  const form = $("#draft-form");
  if (!form) return;
  const dialog = $("#draft-dialog");
  const caption = $("#df-caption"), count = $("#caption-count"), status = $("#df-status"), when = $("#df-when");

  const updateCount = () => { count.textContent = `${caption.value.length} / 3000`; };
  caption.addEventListener("input", updateCount); updateCount();

  if (dialog) {
    $("#new-draft-btn").addEventListener("click", () => { dialog.showModal(); $("#df-topic").focus(); });
    const close = () => dialog.close();
    $("#dialog-close").addEventListener("click", close);
    $("#df-cancel").addEventListener("click", close);
    dialog.addEventListener("click", (e) => { if (e.target === dialog) close(); });
  }

  const clearErrors = () => {
    form.querySelectorAll("[data-error-for]").forEach((p) => { p.textContent = ""; p.classList.add("hidden"); });
    const g = $("#form-error"); g.textContent = ""; g.classList.add("hidden");
  };

  function showErrors(detail) {
    const general = [];
    (Array.isArray(detail) ? detail : []).forEach((d) => {
      const field = d.loc[d.loc.length - 1];
      const slot = form.querySelector(`[data-error-for="${field}"]`);
      if (slot) { slot.textContent = d.msg; slot.classList.remove("hidden"); } else general.push(d.msg);
    });
    if (!Array.isArray(detail)) general.push(String(detail));
    if (general.length) { const g = $("#form-error"); g.textContent = general.join(" "); g.classList.remove("hidden"); }
    const first = form.querySelector("[data-error-for]:not(.hidden)");
    if (first) first.previousElementSibling?.focus?.();
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    clearErrors();
    const edit = form.dataset.mode === "edit";
    const v = (name) => form.elements[name].value;
    const body = {
      platform: v("platform"), content_type: v("content_type"), topic: v("topic"),
      caption: v("caption"), status: v("status"),
      scheduled_for: v("scheduled_for") || null, campaign_id: v("campaign_id") || null,
    };
    const btn = $("#df-submit"); btn.disabled = true;
    try {
      const res = await fetch(edit ? `/api/content/${form.dataset.postId}` : "/api/content/drafts", {
        method: edit ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) { showErrors(json.detail ?? "Something went wrong. Please try again."); return; }
      if (edit) { sessionStorage.setItem("toast", "Changes saved"); location.reload(); }
      else {
        sessionStorage.setItem("toast", body.status === "proposed" ? "Proposed post saved" : "Draft saved");
        location.href = `/content/${json.id}?${window.App.query()}`;
      }
    } catch (err) {
      showErrors("Could not reach the server. Check that it is still running.");
    } finally { btn.disabled = false; }
  });

  // ---- delete ---------------------------------------------------------------------
  const del = $("#delete-btn");
  if (del) del.addEventListener("click", async () => {
    if (!confirm("Delete this post? This cannot be undone (use Settings to reset all demo data).")) return;
    const res = await fetch(`/api/content/${del.dataset.postId}`, { method: "DELETE" });
    if (res.ok) { sessionStorage.setItem("toast", "Deleted"); location.href = `/content?${window.App.query()}`; }
    else window.App.toast("Could not delete this post.");
  });
})();
