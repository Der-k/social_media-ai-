/* Compass - shared front-end behaviour: filters, formatting, refresh, alerts, toasts. */
(function () {
  "use strict";

  const params = new URLSearchParams(location.search);
  const state = {
    days: params.get("days") || "30",
    platform: params.get("platform") || "all",
    campaign: params.get("campaign") || "all",
  };

  const nf0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
  const nfCompact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

  const fmt = {
    int: (v) => nf0.format(v),
    compact: (v) => nfCompact.format(v),
    percent: (v, d = 1) => (v * 100).toFixed(d) + "%",
    money0: (v) => "$" + nf0.format(v),
    money2: (v) => "$" + v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
    ratio: (v) => v.toFixed(2) + "x",
    /** Format by KPI kind; null/undefined means "no value", shown as an em dash. */
    kind(kind, v) {
      if (v === null || v === undefined || Number.isNaN(v)) return "\u2014";
      return (fmt[kind] || fmt.int)(v);
    },
    date(iso) {
      const d = new Date(iso + "T00:00:00");
      return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    },
  };

  const colors = {
    Facebook: "#3b6cf6", Instagram: "#8b5cf6", LinkedIn: "#10a37f", TikTok: "#f0567a",
    blue: "#3563f5", purple: "#7c5cfa", emerald: "#10a37f", red: "#d6455d",
    ink: "#14203b", mute: "#5b6785", line: "#e4e8f1",
  };

  /** Tiny inline-SVG trend line. Null points are skipped. */
  function sparkline(values, tone) {
    const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
    if (pts.length < 2) return "";
    const w = 84, h = 28, ys = pts.map((p) => p[1]);
    const min = Math.min(...ys), max = Math.max(...ys), span = max - min || 1;
    const x = (i) => (i / (values.length - 1)) * w, y = (v) => h - 3 - ((v - min) / span) * (h - 6);
    const d = pts.map(([i, v], k) => (k ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><path d="${d}" fill="none" stroke="${tone}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }

  const $ = (sel, root = document) => root.querySelector(sel);
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const App = (window.App = {
    state, fmt, colors, esc, $, sparkline,
    onFilterChange: null,

    query() { return new URLSearchParams(state).toString(); },

    toast(message, ms = 2800) {
      const el = $("#toast");
      el.textContent = message;
      el.classList.remove("hidden");
      clearTimeout(App._toastTimer);
      App._toastTimer = setTimeout(() => el.classList.add("hidden"), ms);
    },

    markUpdated() {
      $("#last-updated").textContent = new Date().toLocaleTimeString("en-GB");
    },

    syncNavLinks() {
      document.querySelectorAll("a[data-nav]").forEach((a) => { a.href = a.dataset.nav + "?" + App.query(); });
    },

    async loadAlerts() {
      try {
        const res = await fetch("/api/alerts?" + App.query());
        if (!res.ok) throw new Error(res.status);
        const items = await res.json();
        const bad = items.filter((i) => i.severity === "bad").length;
        const badge = $("#bell-badge");
        badge.textContent = bad;
        badge.classList.toggle("hidden", bad === 0);
        badge.classList.toggle("inline-flex", bad > 0);
        const tone = { bad: "#d6455d", good: "#10a37f", info: "#3563f5" };
        $("#bell-list").innerHTML = items.length
          ? items.map((i) => `<li class="flex gap-3 px-4 py-3"><span class="dot mt-1.5" style="background:${tone[i.severity]}"></span>
              <div><div class="font-semibold leading-snug">${esc(i.title)}</div><div class="mt-0.5 text-mute">${esc(i.detail)}</div></div></li>`).join("")
          : `<li class="px-4 py-6 text-center text-mute">No alerts for the selected filters.</li>`;
      } catch (e) {
        $("#bell-list").innerHTML = `<li class="px-4 py-6 text-center text-mute">Alerts could not be loaded.</li>`;
      }
    },

    async refresh() {
      const icon = $("#refresh-icon");
      icon.classList.add("spin");
      try {
        if (App.onFilterChange) await App.onFilterChange();
        else location.reload();
        await App.loadAlerts();
        App.markUpdated();
      } finally {
        setTimeout(() => icon.classList.remove("spin"), 300);
      }
    },
  });

  // ---- filters ---------------------------------------------------------
  document.querySelectorAll("[data-filter]").forEach((el) => {
    el.value = state[el.dataset.filter];
    el.addEventListener("change", async () => {
      state[el.dataset.filter] = el.value;
      // Keep page-specific params (search text, sort, ...) while updating the shared filters.
      const next = new URLSearchParams(location.search);
      Object.entries(state).forEach(([k, v]) => next.set(k, v));
      next.delete("page");
      history.replaceState(null, "", location.pathname + "?" + next.toString());
      App.syncNavLinks();
      if (App.onFilterChange) {
        await App.onFilterChange();
        App.loadAlerts();
        App.markUpdated();
      } else {
        location.reload();
      }
    });
  });

  // ---- chrome: mobile menu, alerts panel, refresh ----------------------
  const sidebar = $("#sidebar"), scrim = $("#scrim");
  const toggleMenu = (open) => {
    sidebar.classList.toggle("-translate-x-full", !open);
    scrim.classList.toggle("hidden", !open);
  };
  $("#menu-btn").addEventListener("click", () => toggleMenu(true));
  scrim.addEventListener("click", () => toggleMenu(false));

  const bellBtn = $("#bell-btn"), bellPanel = $("#bell-panel");
  bellBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const open = bellPanel.classList.toggle("hidden") === false;
    bellBtn.setAttribute("aria-expanded", String(open));
  });
  document.addEventListener("click", (e) => {
    if (!bellPanel.contains(e.target)) { bellPanel.classList.add("hidden"); bellBtn.setAttribute("aria-expanded", "false"); }
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { bellPanel.classList.add("hidden"); toggleMenu(false); }
  });
  $("#refresh-btn").addEventListener("click", () => App.refresh());

  // Randomise every dummy value on the site (optionally with a fixed seed), then reload.
  App.randomize = async (seed) => {
    const btn = $("#randomize-btn"); btn.disabled = true;
    try {
      const res = await fetch("/api/randomize-demo", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ seed: seed === undefined || seed === "" ? null : Number(seed) }) });
      if (!res.ok) throw new Error(res.status);
      const j = await res.json();
      sessionStorage.setItem("toast", j.message + " Reset in Settings restores the original.");
      location.reload();
    } catch (e) { App.toast("Could not randomise the data."); btn.disabled = false; }
  };
  $("#randomize-btn").addEventListener("click", () => App.randomize());

  App.syncNavLinks();
  App.markUpdated();
  App.loadAlerts();

  // A toast queued before a redirect (e.g. "Draft saved").
  const pending = sessionStorage.getItem("toast");
  if (pending) { sessionStorage.removeItem("toast"); App.toast(pending); }
})();
