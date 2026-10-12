/* Dashboard: renders KPIs, charts, heatmap and insight lists from /api/dashboard. */
(function () {
  "use strict";
  const { fmt, colors, esc, $ } = window.App;

  let data = JSON.parse(document.getElementById("dashboard-data").textContent);
  const charts = {};

  Chart.defaults.font.family = '"Figtree", ui-sans-serif, system-ui, sans-serif';
  Chart.defaults.font.size = 12;
  Chart.defaults.color = colors.mute;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;
  Chart.defaults.plugins.legend.labels.boxWidth = 8;
  Chart.defaults.plugins.legend.position = "bottom";

  const gridY = { color: "#eef1f7", drawTicks: false };
  const noGrid = { display: false };
  const baseOptions = () => ({
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: { tooltip: { backgroundColor: colors.ink, padding: 10, cornerRadius: 8, titleFont: { weight: "600" } } },
  });

  function draw(id, config) {
    if (charts[id]) charts[id].destroy();
    charts[id] = new Chart(document.getElementById(id), config);
  }

  const tickEvery = (labels) => ({ autoSkip: true, maxTicksLimit: labels.length > 40 ? 10 : 8, maxRotation: 0 });
  const hasValues = (arr) => arr.some((v) => v !== null && v !== undefined && v > 0);

  // ---- KPI cards -------------------------------------------------------
  function sparkline(values, tone) {
    const pts = values.map((v, i) => [i, v]).filter(([, v]) => v !== null && v !== undefined);
    if (pts.length < 2) return "";
    const w = 84, h = 28, ys = pts.map((p) => p[1]);
    const min = Math.min(...ys), max = Math.max(...ys), span = max - min || 1;
    const x = (i) => (i / (values.length - 1)) * w;
    const y = (v) => h - 3 - ((v - min) / span) * (h - 6);
    const d = pts.map(([i, v], k) => (k ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ");
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><path d="${d}" fill="none" stroke="${tone}" stroke-width="1.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  }

  function renderKpis() {
    const hasPrev = data.meta.has_prev;
    $("#kpi-grid").innerHTML = data.kpis.map((k) => {
      let chip = "";
      if (hasPrev && k.delta !== null) {
        const cls = k.delta_good === null ? "chip-flat" : k.delta_good ? "chip-good" : "chip-bad";
        const arrow = k.delta > 0 ? "\u25B2" : k.delta < 0 ? "\u25BC" : "";
        chip = `<span class="chip ${cls} num">${arrow} ${Math.abs(k.delta * 100).toFixed(1)}%</span>`;
      }
      const tone = k.delta_good === false ? colors.red : colors.blue;
      const missing = k.value === null || k.value === undefined;
      return `<div class="card p-4">
        <div class="flex items-start justify-between gap-2">
          <div class="text-[13px] font-semibold text-mute">${esc(k.label)}</div>${chip}
        </div>
        <div class="num mt-2 text-[28px] font-bold leading-none tracking-tight ${missing ? "text-mute" : ""}">${fmt.kind(k.kind, k.value)}</div>
        <div class="mt-2.5 flex items-end justify-between gap-2">
          <div class="text-[12px] leading-snug ${k.note ? "font-medium text-[#a8730d]" : "text-mute"}">${esc(k.note || k.sub)}</div>
          ${sparkline(k.spark, tone)}
        </div>
      </div>`;
    }).join("");
  }

  // ---- signals ---------------------------------------------------------
  function renderSignals() {
    const tone = { good: colors.emerald, bad: colors.red, info: colors.mute };
    $("#signals").innerHTML = data.signals.map((s) => `
      <div class="bg-white px-5 py-4">
        <div class="flex items-center gap-2 text-[12.5px] font-semibold text-mute"><span class="dot" style="background:${tone[s.tone]}"></span>${esc(s.label)}</div>
        <div class="mt-1.5 text-[19px] font-bold tracking-tight">${esc(s.value)}</div>
        <div class="mt-0.5 text-[12.5px] leading-snug text-mute">${esc(s.detail)}</div>
      </div>`).join("");
  }

  // ---- charts ----------------------------------------------------------
  function renderCharts() {
    const s = data.series;

    draw("chart-engagement", {
      type: "line",
      data: {
        labels: s.labels,
        datasets: [
          { label: "Engagements", data: s.engagements, borderColor: colors.blue, backgroundColor: "rgba(53,99,245,.10)", fill: true, tension: .3, pointRadius: 0, pointHoverRadius: 4, borderWidth: 2, yAxisID: "y" },
          { label: "Engagement rate (%)", data: s.engagement_rate, borderColor: colors.purple, borderDash: [5, 4], tension: .3, pointRadius: 0, pointHoverRadius: 4, borderWidth: 2, spanGaps: true, yAxisID: "y1" },
        ],
      },
      options: {
        ...baseOptions(),
        scales: {
          x: { grid: noGrid, ticks: tickEvery(s.labels) },
          y: { beginAtZero: true, grid: gridY, border: { display: false }, ticks: { callback: (v) => fmt.compact(v) } },
          y1: { position: "right", beginAtZero: true, grid: noGrid, border: { display: false }, ticks: { callback: (v) => v + "%" } },
        },
      },
    });

    draw("chart-reach", {
      type: "line",
      data: {
        labels: s.labels,
        datasets: [
          { label: "Impressions", data: s.impressions, borderColor: colors.blue, tension: .3, pointRadius: 0, pointHoverRadius: 4, borderWidth: 2 },
          { label: "Reach", data: s.reach, borderColor: colors.emerald, backgroundColor: "rgba(16,163,127,.10)", fill: true, tension: .3, pointRadius: 0, pointHoverRadius: 4, borderWidth: 2 },
        ],
      },
      options: {
        ...baseOptions(),
        scales: {
          x: { grid: noGrid, ticks: tickEvery(s.labels) },
          y: { beginAtZero: true, grid: gridY, border: { display: false }, ticks: { callback: (v) => fmt.compact(v) } },
        },
      },
    });

    const anyConv = s.conversions.some((v) => v !== null);
    $("#spend-note").classList.toggle("hidden", anyConv);
    draw("chart-spend", {
      data: {
        labels: s.labels,
        datasets: [
          { type: "bar", label: "Spend ($)", data: s.spend, backgroundColor: "rgba(53,99,245,.28)", hoverBackgroundColor: "rgba(53,99,245,.5)", borderRadius: 4, yAxisID: "y", order: 2 },
          { type: "line", label: "Conversions", data: s.conversions, borderColor: colors.emerald, backgroundColor: colors.emerald, tension: .3, pointRadius: 2, pointHoverRadius: 5, borderWidth: 2, spanGaps: false, yAxisID: "y1", order: 1 },
        ],
      },
      options: {
        ...baseOptions(),
        scales: {
          x: { grid: noGrid, ticks: tickEvery(s.labels) },
          y: { beginAtZero: true, grid: gridY, border: { display: false }, ticks: { callback: (v) => "$" + fmt.compact(v) } },
          y1: { position: "right", beginAtZero: true, grid: noGrid, border: { display: false }, ticks: { precision: 0 } },
        },
      },
    });

    const pl = data.platforms;
    draw("chart-platform", {
      data: {
        labels: pl.map((p) => p.platform),
        datasets: [
          { type: "bar", label: "Reach", data: pl.map((p) => p.reach), backgroundColor: pl.map((p) => colors[p.platform] + (data.meta.platform !== "all" && data.meta.platform !== p.platform ? "55" : "cc")), borderRadius: 6, yAxisID: "y", order: 2 },
          { type: "line", label: "Engagement rate (%)", data: pl.map((p) => (p.engagement_rate === null ? null : +(p.engagement_rate * 100).toFixed(2))), showLine: false, pointStyle: "rectRot", pointRadius: 7, pointBackgroundColor: "#fff", pointBorderColor: colors.ink, pointBorderWidth: 2, yAxisID: "y1", order: 1 },
        ],
      },
      options: {
        ...baseOptions(),
        scales: {
          x: { grid: noGrid },
          y: { beginAtZero: true, grid: gridY, border: { display: false }, ticks: { callback: (v) => fmt.compact(v) } },
          y1: { position: "right", beginAtZero: true, grid: noGrid, border: { display: false }, ticks: { callback: (v) => v + "%" } },
        },
      },
    });

    const top = data.top_posts;
    draw("chart-top", {
      type: "bar",
      data: {
        labels: top.map((p) => p.label),
        datasets: [{ label: "Engagement rate (%)", data: top.map((p) => p.engagement_rate), backgroundColor: top.map((p) => colors[p.platform]), borderRadius: 6, barThickness: 22 }],
      },
      options: {
        ...baseOptions(), indexAxis: "y", interaction: { mode: "nearest", intersect: true },
        plugins: {
          legend: { display: false },
          tooltip: {
            ...baseOptions().plugins.tooltip,
            callbacks: {
              title: (items) => top[items[0].dataIndex].caption.slice(0, 80) + (top[items[0].dataIndex].caption.length > 80 ? "..." : ""),
              label: (item) => { const p = top[item.dataIndex]; return `${p.platform}: ${p.engagement_rate}% engagement, ${fmt.int(p.reach)} reach (${fmt.date(p.published)})`; },
            },
          },
        },
        scales: {
          x: { beginAtZero: true, grid: gridY, border: { display: false }, ticks: { callback: (v) => v + "%" } },
          y: { grid: noGrid, ticks: { callback(v) { const l = this.getLabelForValue(v); return l.length > 34 ? l.slice(0, 33) + "\u2026" : l; } } },
        },
      },
    });
  }

  // ---- heatmap ---------------------------------------------------------
  function renderHeatmap() {
    const h = data.heatmap;
    const all = h.cells.flat().filter((c) => c.n > 0 && c.er !== null).map((c) => c.er);
    const min = Math.min(...all), max = Math.max(...all), span = max - min || 1;
    let html = '<div class="heat" role="table" aria-label="Engagement rate by weekday and time of day"><div></div>';
    h.dayparts.forEach((d, i) => { html += `<div class="heat-head" role="columnheader">${d}<br><span class="opacity-70">${h.ranges[i]}</span></div>`; });
    h.cells.forEach((row, w) => {
      html += `<div class="heat-row" role="rowheader">${h.days[w]}</div>`;
      row.forEach((c, d) => {
        const isBest = h.best && h.best.weekday === w && h.best.daypart === d;
        if (!c.n || c.er === null) { html += `<div class="heat-cell" style="background:#f1f3f9;color:#c3cad9" title="No posts">\u00B7</div>`; return; }
        const t = (c.er - min) / span;
        const fade = c.n === 1 ? ";opacity:.6" : "";
        html += `<div class="heat-cell num" style="background:rgba(16,163,127,${(0.12 + 0.73 * t).toFixed(2)});color:${t > 0.55 ? "#fff" : colors.ink}${fade}${isBest ? ";outline:2px solid " + colors.purple + ";outline-offset:1px" : ""}"
             title="${h.days[w]} ${h.dayparts[d]}: ${(c.er * 100).toFixed(1)}% engagement across ${c.n} post${c.n > 1 ? "s" : ""}${c.n === 1 ? " (low sample)" : ""}">${(c.er * 100).toFixed(1)}</div>`;
      });
    });
    html += "</div>";
    $("#heatmap").innerHTML = html;
    const mixed = data.meta.platform === "all" ? " Mixed platforms: filter by platform for cleaner windows." : "";
    const bestTxt = h.best ? ` Purple outline marks the strongest slot with at least ${h.best.n >= 3 ? 3 : 2} posts.` : "";
    $("#heat-sub").textContent = `Engagement rate (%) by weekday and time of day, from ${h.total_posts} posts. Faded cells have a single post.${bestTxt}${mixed}`;
  }

  // ---- lists -----------------------------------------------------------
  function renderChanges() {
    const tone = { bad: colors.red, good: colors.emerald, info: colors.blue };
    $("#changes").innerHTML = data.changes.length
      ? data.changes.map((c) => `<li class="flex gap-3 px-5 py-3.5"><span class="dot mt-[7px]" style="background:${tone[c.severity]}"></span>
          <div class="min-w-0"><div class="text-[13.5px] font-semibold leading-snug">${esc(c.title)}</div>
          <div class="mt-0.5 text-[12.5px] leading-snug text-mute">${esc(c.detail)}</div></div></li>`).join("")
      : `<li class="px-5 py-8 text-center text-[13.5px] text-mute">No notable changes for these filters.</li>`;
  }

  function renderActivity() {
    const label = { post: "Published", proposal: "Proposed", draft: "Draft", campaign: "Campaign" };
    $("#activity").innerHTML = data.activity.length
      ? data.activity.map((a) => `<li class="flex gap-3 px-5 py-3">
          <span class="dot mt-[7px]" style="background:${colors[a.platform] || colors.mute}"></span>
          <div class="min-w-0 flex-1"><div class="flex items-baseline justify-between gap-2">
            <div class="truncate text-[13.5px] font-semibold">${esc(a.title)}</div>
            <div class="flex-none text-[12px] text-mute">${esc(a.when)}</div></div>
            <div class="mt-0.5 line-clamp-2 text-[12.5px] leading-snug text-mute">${esc(a.detail)}</div></div></li>`).join("")
      : `<li class="px-5 py-8 text-center text-[13.5px] text-mute">No activity for these filters.</li>`;
  }

  function renderHeader() {
    const m = data.meta;
    let txt = `${fmt.date(m.start)} to ${fmt.date(m.end)}`;
    txt += m.has_prev ? `, compared with the previous ${m.days} days` : ", no earlier period available to compare";
    if (m.platform !== "all") txt += ` \u00B7 ${m.platform} only`;
    if (m.campaign_name) txt += ` \u00B7 ${m.campaign_name}`;
    $("#period-label").textContent = txt;
  }

  function render() {
    renderHeader(); renderKpis(); renderSignals(); renderCharts();
    renderHeatmap(); renderChanges(); renderActivity();
  }

  window.App.onFilterChange = async function () {
    const body = $("#page-body");
    body.classList.add("skeleton-fade");
    try {
      const res = await fetch("/api/dashboard?" + window.App.query());
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
