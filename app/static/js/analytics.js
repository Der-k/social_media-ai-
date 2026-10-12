/* Social Analytics: renders organic KPIs, charts, tables and the posting-time heatmap from /api/analytics. */
(function () {
  "use strict";
  const { fmt, colors, esc, $, sparkline } = window.App;

  let data = JSON.parse(document.getElementById("analytics-data").textContent);
  const charts = {};
  const view = { mix: "platform", heat: "er", sort: { key: "er", dir: -1 } };
  const MIX_COLORS = { likes: colors.blue, comments: colors.purple, shares: colors.emerald, saves: "#e0a526" };

  Chart.defaults.font.family = '"Figtree", ui-sans-serif, system-ui, sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = colors.mute;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.position = "bottom";

  const gridY = { color: "#eef1f7", drawTicks: false };
  const noGrid = { display: false };
  const tip = { backgroundColor: colors.ink, padding: 10, cornerRadius: 8, titleFont: { weight: "600" } };
  const base = () => ({ responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false }, plugins: { tooltip: { ...tip } } });
  const pctTick = (v) => v + "%";
  const compact = (v) => fmt.compact(v);

  function draw(id, config) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), config);
  }
  const empty = (id, msg) => {   // overlay message instead of an empty chart
    const host = document.getElementById(id).parentElement;
    let el = host.querySelector("[data-empty]");
    if (!msg) { el?.remove(); return; }
    if (!el) { el = document.createElement("div"); el.dataset.empty = ""; el.className = "absolute inset-0 flex items-center justify-center bg-white/90 px-6 text-center text-[13.5px] text-mute"; host.appendChild(el); }
    el.textContent = msg;
  };

  // ---- header, KPIs, insights, scorecards ----------------------------------------
  function renderHeader() {
    const m = data.meta;
    let t = `${fmt.date(m.start)} to ${fmt.date(m.end)} \u00B7 ${fmt.int(m.posts)} published posts`;
    t += m.has_prev ? `, compared with the previous ${m.days} days` : ", no earlier period to compare";
    if (m.platform !== "all") t += ` \u00B7 ${m.platform} only`;
    $("#period-label").textContent = t;
    $("#ask-ai").href = `/assistant?${window.App.query()}&ask=` + encodeURIComponent("Explain what is driving organic engagement in the selected range and what stands out.");
  }

  function renderKpis() {
    $("#kpi-grid").innerHTML = data.kpis.map((k) => {
      let chip = "";
      if (data.meta.has_prev && k.delta !== null) {
        const cls = k.delta_good === null ? "chip-flat" : k.delta_good ? "chip-good" : "chip-bad";
        chip = `<span class="chip ${cls} num">${k.delta > 0 ? "\u25B2" : k.delta < 0 ? "\u25BC" : ""} ${Math.abs(k.delta * 100).toFixed(1)}%</span>`;
      }
      const missing = k.value === null || k.value === undefined;
      return `<div class="card p-4">
        <div class="flex items-start justify-between gap-2"><div class="text-[13px] font-semibold text-mute">${esc(k.label)}</div>${chip}</div>
        <div class="num mt-2 text-[28px] font-bold leading-none tracking-tight ${missing ? "text-mute" : ""}">${fmt.kind(k.kind, k.value)}</div>
        <div class="mt-2.5 flex items-end justify-between gap-2">
          <div class="text-[12px] leading-snug ${k.note ? "font-medium text-[#a8730d]" : "text-mute"}">${esc(k.note || k.sub)}</div>
          ${sparkline(k.spark, k.delta_good === false ? colors.red : colors.blue)}</div></div>`;
    }).join("");
  }

  function renderInsights() {
    const tone = { good: colors.emerald, bad: colors.red, info: colors.mute };
    $("#insights").innerHTML = data.insights.map((i) => `<div class="bg-white px-5 py-4">
      <div class="flex items-start gap-2"><span class="dot mt-[7px]" style="background:${tone[i.tone]}"></span>
        <div><div class="text-[14px] font-semibold leading-snug">${esc(i.title)}</div><div class="mt-0.5 text-[12.5px] leading-snug text-mute">${esc(i.detail)}</div></div></div></div>`).join("");
  }

  function renderScorecards() {
    const sel = data.meta.platform;
    $("#scorecards").innerHTML = data.scorecards.map((s) => {
      let chip = "";
      if (data.meta.has_prev && s.er_delta !== null) {
        chip = `<span class="chip ${s.er_delta >= 0 ? "chip-good" : "chip-bad"} num">${s.er_delta > 0 ? "\u25B2" : "\u25BC"} ${Math.abs(s.er_delta * 100).toFixed(1)}%</span>`;
      }
      const body = s.posts
        ? `<div class="num mt-2 text-[26px] font-bold leading-none tracking-tight">${fmt.kind("percent", s.er)}</div>
           <div class="mt-0.5 text-[12px] text-mute">engagement rate</div>
           <dl class="mt-3 grid grid-cols-2 gap-x-3 gap-y-1.5 text-[12.5px]">
             <div><dt class="text-mute">Posts</dt><dd class="num font-semibold">${s.posts}</dd></div>
             <div><dt class="text-mute">Reach</dt><dd class="num font-semibold">${fmt.compact(s.reach)}</dd></div>
             <div><dt class="text-mute">Avg reach/post</dt><dd class="num font-semibold">${fmt.int(s.avg_reach)}</dd></div>
             <div><dt class="text-mute">Saves+shares</dt><dd class="num font-semibold">${fmt.kind("percent", s.saves_shares)}</dd></div>
           </dl>`
        : `<div class="mt-3 text-[13px] text-mute">No posts in this range.</div>`;
      return `<div class="card p-4 ${sel === s.platform ? "ring-2 ring-signal" : ""}">
        <div class="flex items-center justify-between gap-2"><div class="inline-flex items-center gap-2 text-[14px] font-bold"><span class="dot" style="background:${colors[s.platform]}"></span>${s.platform}</div>${chip}</div>${body}</div>`;
    }).join("");
  }

  // ---- charts ------------------------------------------------------------------------
  function renderTrend() {
    const t = data.trend, names = Object.keys(t.er);
    $("#trend-sub").textContent = t.granularity === "day"
      ? "Engagements / reach for each day. Days without posts are gaps."
      : "Engagements / reach for each 7-day period ending on the last day of the range. Periods without posts are gaps. A shorter first period is labelled with its length.";
    const any = names.some((n) => t.er[n].some((v) => v !== null));
    empty("chart-trend", any ? "" : "No posts in this range.");
    draw("chart-trend", {
      type: "line",
      data: { labels: t.labels, datasets: names.map((n) => ({ label: n, data: t.er[n], borderColor: colors[n], backgroundColor: colors[n], tension: .3, spanGaps: true, pointRadius: 3, pointHoverRadius: 5, borderWidth: 2 })) },
      options: { ...base(), scales: { x: { grid: noGrid, ticks: { autoSkip: true, maxTicksLimit: 8, maxRotation: 0 } }, y: { beginAtZero: true, grid: gridY, border: { display: false }, ticks: { callback: pctTick } } } },
    });
  }

  function renderMix() {
    const rows = data.mix[view.mix];
    document.querySelectorAll("[data-mix]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.mix === view.mix));
    empty("chart-mix", rows.length ? "" : "No engagement in this range.");
    draw("chart-mix", {
      type: "bar",
      data: { labels: rows.map((r) => `${r.label} (${r.n})`), datasets: ["likes", "comments", "shares", "saves"].map((k) => ({ label: k[0].toUpperCase() + k.slice(1), data: rows.map((r) => +(r[k] || 0).toFixed(1)), backgroundColor: MIX_COLORS[k], borderWidth: 0 })) },
      options: { ...base(), indexAxis: "y", interaction: { mode: "nearest", intersect: true },
        plugins: { tooltip: { ...tip, callbacks: { label: (i) => `${i.dataset.label}: ${i.parsed.x}%` } } },
        scales: { x: { stacked: true, max: 100, grid: gridY, border: { display: false }, ticks: { callback: pctTick } }, y: { stacked: true, grid: noGrid } } },
    });
  }

  function renderCadence() {
    const t = data.trend, names = Object.keys(t.posts);
    const any = names.some((n) => t.posts[n].some((v) => v > 0));
    empty("chart-cadence", any ? "" : "No posts in this range.");
    draw("chart-cadence", {
      data: { labels: t.labels, datasets: [
        ...names.map((n) => ({ type: "bar", label: n, data: t.posts[n], backgroundColor: colors[n] + "bb", borderRadius: 3, stack: "posts", yAxisID: "y", order: 2 })),
        { type: "line", label: "Engagement rate", data: t.overall_er, borderColor: colors.ink, borderDash: [5, 4], tension: .3, spanGaps: true, pointRadius: 2, borderWidth: 2, yAxisID: "y1", order: 1 },
      ] },
      options: { ...base(), scales: { x: { stacked: true, grid: noGrid, ticks: { autoSkip: true, maxTicksLimit: 6, maxRotation: 0 } },
        y: { stacked: true, beginAtZero: true, grid: gridY, border: { display: false }, ticks: { precision: 0 }, title: { display: true, text: "Posts" } },
        y1: { position: "right", beginAtZero: true, grid: noGrid, border: { display: false }, ticks: { callback: pctTick } } } },
    });
  }

  function renderScatter() {
    const pts = data.scatter, m = data.meta;
    empty("chart-scatter", pts.length ? "" : "No posts in this range.");
    const maxX = Math.max(1, ...pts.map((p) => p.x)) * 1.05, maxY = Math.max(1, ...pts.map((p) => p.y)) * 1.1;
    const platforms = [...new Set(pts.map((p) => p.platform))];
    const means = [];
    if (pts.length) {
      means.push({ type: "line", label: "Average reach", isMean: true, data: [{ x: m.mean_reach, y: 0 }, { x: m.mean_reach, y: maxY }], borderColor: "#9aa6c3", borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5 });
      means.push({ type: "line", label: "Average engagement", isMean: true, data: [{ x: 0, y: m.mean_er }, { x: maxX, y: m.mean_er }], borderColor: "#9aa6c3", borderDash: [5, 4], pointRadius: 0, borderWidth: 1.5 });
    }
    draw("chart-scatter", {
      type: "scatter",
      data: { datasets: [...platforms.map((pl) => ({ type: "scatter", label: pl, data: pts.filter((p) => p.platform === pl), backgroundColor: colors[pl] + "b3", borderColor: colors[pl], pointRadius: 4.5, pointHoverRadius: 7 })), ...means] },
      options: { ...base(), interaction: { mode: "nearest", intersect: true },
        onClick: (e, els, chart) => { const el = els[0]; if (!el) return; const p = chart.data.datasets[el.datasetIndex].data[el.index]; if (p && p.id) location.href = `/content/${p.id}?${window.App.query()}`; },
        onHover: (e, els) => { e.native.target.style.cursor = els.length && els[0] && charts["chart-scatter"].data.datasets[els[0].datasetIndex].isMean !== true ? "pointer" : "default"; },
        plugins: { legend: { labels: { filter: (i, d) => !d.datasets[i.datasetIndex].isMean } },
          tooltip: { ...tip, filter: (i) => !i.dataset.isMean, callbacks: {
            title: (items) => { const p = items[0].raw; return p.caption + (p.caption.length >= 90 ? "..." : ""); },
            label: (i) => { const p = i.raw; return `${p.platform} ${p.type.toLowerCase()}, ${fmt.date(p.date)}: ${fmt.int(p.x)} reach, ${p.y}% engagement`; } } } },
        scales: { x: { min: 0, max: maxX, grid: gridY, border: { display: false }, ticks: { callback: compact }, title: { display: true, text: "Reach" } },
                  y: { min: 0, max: maxY, grid: gridY, border: { display: false }, ticks: { callback: pctTick }, title: { display: true, text: "Engagement rate" } } } },
    });
  }

  function renderTopics() {
    const rows = data.topics, avg = data.meta.mean_er;
    empty("chart-topics", rows.length ? "" : "Not enough posts per topic (needs 2+).");
    draw("chart-topics", {
      type: "bar",
      data: { labels: rows.map((r) => `${r.label} (${r.n})`), datasets: [{ label: "Engagement rate (%)", data: rows.map((r) => +(r.er * 100).toFixed(2)), backgroundColor: rows.map((r) => (avg !== null && r.er * 100 >= avg ? colors.blue : "#aab6d3")), borderRadius: 5, barThickness: 20 }] },
      options: { ...base(), indexAxis: "y", interaction: { mode: "nearest", intersect: true },
        plugins: { legend: { display: false }, tooltip: { ...tip, callbacks: { label: (i) => { const r = rows[i.dataIndex]; return `${r.er ? (r.er * 100).toFixed(1) : "-"}% engagement, ${r.n} posts, ${fmt.int(r.avg_reach)} avg reach, ${r.saves_pp.toFixed(0)} saves/post`; } } } },
        scales: { x: { beginAtZero: true, grid: gridY, border: { display: false }, ticks: { callback: pctTick } }, y: { grid: noGrid } } },
    });
  }

  // ---- tables and grids -----------------------------------------------------------------
  const COLS = [["label", "Format", false], ["n", "Posts", true], ["er", "Eng. rate", true], ["avg_reach", "Avg reach", true],
                ["saves_pp", "Saves / post", true], ["shares_pp", "Shares / post", true], ["comments_pp", "Comments / post", true], ["clicks_pp", "Clicks / post", true]];

  function renderFormats() {
    const { key, dir } = view.sort;
    const rows = [...data.formats].sort((a, b) => {
      const x = a[key], y = b[key];
      if (typeof x === "string") return dir * x.localeCompare(y);
      return dir * ((x ?? -Infinity) - (y ?? -Infinity));
    });
    const maxEr = Math.max(0.0001, ...rows.map((r) => r.er || 0));
    const head = COLS.map(([k, label, num]) => `<th class="sortable px-3 py-2.5 font-semibold ${num ? "text-right" : "pl-5"}" data-sort="${k}" aria-sort="${key === k ? (dir > 0 ? "ascending" : "descending") : "none"}">${label}${key === k ? (dir > 0 ? " \u25B2" : " \u25BC") : ""}</th>`).join("");
    const body = rows.length ? rows.map((r) => {
      const chip = r.lift === null ? "" : `<span class="chip ${r.lift >= 1.05 ? "chip-good" : r.lift <= 0.95 ? "chip-bad" : "chip-flat"} num">${r.lift >= 1 ? "+" : ""}${((r.lift - 1) * 100).toFixed(0)}%</span>`;
      return `<tr class="${r.thin ? "opacity-60" : ""}"><td class="py-3 pl-5 pr-3 font-semibold">${esc(r.label)}${r.thin ? ' <span class="text-[11.5px] font-normal text-mute">(thin)</span>' : ""}</td>
        <td class="num px-3 py-3 text-right">${r.n}</td>
        <td class="num px-3 py-3 text-right"><div class="flex items-center justify-end gap-2"><span class="hidden h-1.5 w-14 overflow-hidden rounded-full bg-[#eef1f7] sm:block"><span class="block h-full rounded-full bg-signal" style="width:${((r.er || 0) / maxEr * 100).toFixed(0)}%"></span></span><span class="font-semibold">${fmt.kind("percent", r.er)}</span>${chip}</div></td>
        <td class="num px-3 py-3 text-right">${fmt.int(r.avg_reach)}</td><td class="num px-3 py-3 text-right">${r.saves_pp.toFixed(0)}</td>
        <td class="num px-3 py-3 text-right">${r.shares_pp.toFixed(0)}</td><td class="num px-3 py-3 text-right">${r.comments_pp.toFixed(0)}</td><td class="num px-3 py-3 text-right">${r.clicks_pp.toFixed(0)}</td></tr>`;
    }).join("") : `<tr><td colspan="8" class="px-5 py-10 text-center text-mute">No posts in this range.</td></tr>`;
    $("#format-table").innerHTML = `<thead class="bg-[#fafbfe] text-[12.5px] text-mute"><tr>${head}</tr></thead><tbody class="divide-y divide-line">${body}</tbody>`;
  }

  function renderMatrix() {
    const plats = data.matrix[0].cells.map((c) => c.platform);
    let html = `<div class="grid min-w-[560px] gap-1.5" style="grid-template-columns:140px repeat(${plats.length},minmax(0,1fr))"><div></div>` +
      plats.map((p) => `<div class="pb-1 text-center text-[12.5px] font-semibold"><span class="dot mr-1" style="background:${colors[p]}"></span>${p}</div>`).join("");
    data.matrix.forEach((row) => {
      html += `<div class="flex items-center text-[13px] font-medium">${esc(row.label)}</div>`;
      row.cells.forEach((c) => {
        if (!c.n || c.lift === null) { html += `<div class="grid h-12 place-items-center rounded-lg bg-[#f1f3f9] text-[12px] text-[#b3bbcf]" title="No posts">no posts</div>`; return; }
        const up = c.lift >= 1, a = up ? Math.min(0.14 + (c.lift - 1) * 1.1, 0.85) : Math.min(0.14 + (1 - c.lift) * 1.1, 0.8);
        html += `<div class="num grid h-12 place-items-center rounded-lg text-center leading-tight" style="background:${up ? `rgba(16,163,127,${a.toFixed(2)})` : `rgba(214,69,93,${a.toFixed(2)})`};color:${a > 0.55 ? "#fff" : colors.ink};${c.n < 3 ? "opacity:.55" : ""}"
          title="${esc(row.label)} on ${c.platform}: ${(c.er * 100).toFixed(1)}% engagement, ${c.n} posts, ${((c.lift - 1) * 100).toFixed(0)}% vs platform average${c.n < 3 ? " (thin sample)" : ""}">
          <span class="text-[13px] font-bold">${(c.er * 100).toFixed(1)}%</span><span class="text-[10.5px] opacity-80">n=${c.n}</span></div>`;
      });
    });
    $("#matrix").innerHTML = html + "</div>";
  }

  function renderWindows() {
    $("#windows").innerHTML = data.windows.map((w) => {
      const row = (label, o) => `<div class="mt-1 text-[12.5px]"><span class="text-mute">${label}:</span> ${o ? `<span class="font-semibold">${esc(o.label)}</span> <span class="num text-mute">${(o.er * 100).toFixed(1)}%, n=${o.n}</span>` : '<span class="text-mute">not enough data</span>'}</div>`;
      return `<li class="px-5 py-3"><div class="flex items-center justify-between"><span class="inline-flex items-center gap-2 text-[13.5px] font-bold"><span class="dot" style="background:${colors[w.platform]}"></span>${w.platform}</span><span class="text-[12px] text-mute">${w.posts} posts</span></div>
        ${row("Time of day", w.daypart)}${row("Weekday", w.weekday)}</li>`;
    }).join("");
  }

  function renderHeatmap() {
    const h = data.heatmap, k = view.heat;
    document.querySelectorAll("[data-heat]").forEach((b) => b.setAttribute("aria-pressed", b.dataset.heat === k));
    const vals = h.cells.flat().filter((c) => c.n > 0 && c[k] !== null && c[k] !== undefined).map((c) => c[k]);
    const min = Math.min(...vals), max = Math.max(...vals), span = max - min || 1;
    const show = (v) => (k === "er" ? (v * 100).toFixed(1) : k === "avg_reach" ? fmt.compact(v) : String(v));
    const label = { er: "engagement rate (%)", avg_reach: "average reach per post", n: "number of posts" }[k];
    const best = h.best[k];
    let html = '<div class="heat" role="table"><div></div>' + h.dayparts.map((d, i) => `<div class="heat-head" role="columnheader">${d}<br><span class="opacity-70">${h.ranges[i]}</span></div>`).join("");
    h.cells.forEach((row, w) => {
      html += `<div class="heat-row" role="rowheader">${h.days[w]}</div>`;
      row.forEach((c, d) => {
        if (!c.n || c[k] === null) { html += `<div class="heat-cell" style="background:#f1f3f9;color:#c3cad9" title="No posts">\u00B7</div>`; return; }
        const t = (c[k] - min) / span, isBest = best && best.weekday === w && best.daypart === d;
        html += `<div class="heat-cell num" style="background:rgba(16,163,127,${(0.12 + 0.73 * t).toFixed(2)});color:${t > 0.55 ? "#fff" : colors.ink};${c.n === 1 ? "opacity:.6;" : ""}${isBest ? `outline:2px solid ${colors.purple};outline-offset:1px` : ""}"
          title="${h.days[w]} ${h.dayparts[d]}: ${show(c[k])} (${c.n} post${c.n > 1 ? "s" : ""}${c.n === 1 ? ", low sample" : ""})">${show(c[k])}</div>`;
      });
    });
    $("#heatmap").innerHTML = html + "</div>";
    const mixed = data.meta.platform === "all" ? " Platforms are mixed, so filter by one for a cleaner read." : "";
    $("#heat-sub").textContent = `Showing ${label} from ${h.total} posts across all history.${best ? ` Purple outline: ${best.label} (${best.n} posts).` : ""}${mixed}`;
  }

  function render() {
    renderHeader(); renderKpis(); renderInsights(); renderScorecards(); renderTrend(); renderMix(); renderCadence();
    renderScatter(); renderTopics(); renderFormats(); renderMatrix(); renderWindows(); renderHeatmap();
  }

  // ---- interactions -------------------------------------------------------------------------
  document.addEventListener("click", (e) => {
    const mix = e.target.closest("[data-mix]"), heat = e.target.closest("[data-heat]"), th = e.target.closest("[data-sort]");
    if (mix) { view.mix = mix.dataset.mix; renderMix(); }
    if (heat) { view.heat = heat.dataset.heat; renderHeatmap(); }
    if (th) {
      const k = th.dataset.sort;
      view.sort = { key: k, dir: view.sort.key === k ? -view.sort.dir : (k === "label" ? 1 : -1) };
      renderFormats();
    }
  });

  window.App.onFilterChange = async function () {
    const body = $("#page-body");
    body.classList.add("skeleton-fade");
    try {
      const res = await fetch("/api/analytics?" + window.App.query());
      if (!res.ok) throw new Error("HTTP " + res.status);
      data = await res.json();
      render();
    } catch (err) {
      window.App.toast("Could not refresh. Showing the previous data.");
    } finally {
      body.classList.remove("skeleton-fade");
    }
  };

  render();
})();
