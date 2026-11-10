// Shared chart builders for study pages, imported from OJS cells as a local ES module:
//   import {timeSeries, ranking} from "../../assets/charts.js"
// Plotly is passed in from the calling cell (Plotly = require("plotly.js-dist-min@2.35.2")),
// since this plain module cannot use OJS's own module resolution.
//
// Every chart gets: hover tooltips, drag-to-zoom + pan, double-click to reset, a clickable
// legend (click hides a series), and, for time series, period shortcuts + the events overlay.

const PALETTE = ["#0f766e", "#d97706", "#7c3aed", "#dc2626", "#2563eb", "#64748b", "#be185d"];
// Events share one neutral colour so they never read as another data series; scope (PT/EU/World)
// is stated in the tooltip and the evidence grade by marker shape (see the legend).
const EVENT_COLOR = "#475569";
const SCOPE_LABEL = {
  pt: { PT: "Portugal", EU: "União Europeia", World: "Mundo" },
  en: { PT: "Portugal", EU: "European Union", World: "World" },
};
const GRADE_SYMBOL = { A: "diamond", B: "diamond-open", C: "circle-open" };
const GRADE_LABEL = {
  pt: {
    A: "Evento · grau A (a fonte estabelece a relação)",
    B: "Evento · grau B (mecanismo plausível)",
    C: "Evento · grau C (só coincidência temporal)",
  },
  en: {
    A: "Event · grade A (source establishes the link)",
    B: "Event · grade B (plausible mechanism)",
    C: "Event · grade C (temporal coincidence only)",
  },
};
const TEXT = {
  pt: { hintShort: "Arraste para fazer zoom · duplo clique repõe", all: "Tudo", year: "a", scope: "Âmbito", source: "Fonte", hint: "Arraste para fazer zoom · duplo clique repõe · clique na legenda para ocultar" },
  en: { hintShort: "Drag to zoom · double-click to reset", all: "All", year: "y", scope: "Scope", source: "Source", hint: "Drag to zoom · double-click to reset · click the legend to hide a series" },
};

function baseLayout(opts) {
  const style = getComputedStyle(document.body);
  return {
    font: { family: style.fontFamily, size: 13, color: "#1f2937" },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    margin: { l: 56, r: 16, t: opts.title ? 48 : 16, b: 40 },
    title: opts.title ? { text: opts.title, x: 0, font: { size: 15 } } : undefined,
    hoverlabel: { bgcolor: "#111827", font: { color: "#f9fafb", size: 13 }, bordercolor: "#111827" },
    dragmode: "zoom",
    hovermode: "closest",
    legend: { orientation: "h", x: 0, y: -0.22, font: { size: 12 } },
    xaxis: { showgrid: false, linecolor: "#cbd5e1", ticks: "outside", tickcolor: "#cbd5e1", automargin: true },
    yaxis: { gridcolor: "#e5e7eb", zeroline: false, automargin: true, title: { text: opts.yTitle || "", standoff: 8 } },
  };
}

function baseConfig(filename) {
  return {
    responsive: true,
    displaylogo: false,
    scrollZoom: false,
    doubleClick: "reset",
    modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"],
    toImageButtonOptions: { format: "png", filename, scale: 2 },
  };
}

function mount(Plotly, traces, layout, config, hint) {
  const wrapper = document.createElement("div");
  wrapper.className = "chart-block";
  const plot = document.createElement("div");
  plot.className = "chart-plot";
  wrapper.appendChild(plot);
  const note = document.createElement("div");
  note.className = "chart-hint";
  note.textContent = hint;
  wrapper.appendChild(note);
  Plotly.newPlot(plot, traces, layout, config);
  // The container's width can still change after the first paint (scrollbars, TOC layout,
  // rotating a phone), and Plotly only measures once: follow the wrapper explicitly.
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(() => Plotly.Plots.resize(plot)).observe(wrapper);
  }
  return wrapper;
}

/**
 * Time series with legend, tooltips, zoom, period shortcuts and an events overlay.
 *
 * @param {object} Plotly
 * @param {Array<object>} data - canonical long rows: {data, region, sex, age, value, unit, ...}
 * @param {object} opts
 *   groupBy   field that defines one line per value (default "region")
 *   labels    optional map from raw group value to display name
 *   unit      unit shown in tooltips (default: first row's `unit`)
 *   yTitle    y axis title
 *   title     optional chart title
 *   events   events to overlay, each with start_date, end_date?, scope, grade, title_pt/en,
 *             primary_source_url (see site/build.py's linked_events.json)
 *   lang      "pt" | "en"
 */
export function timeSeries(Plotly, data, opts = {}) {
  const { groupBy = "region", labels = {}, events = [], lang = "pt", height = 440 } = opts;
  const t = TEXT[lang];
  const unit = opts.unit || (data[0] && data[0].unit) || "";
  const groups = [...new Set(data.map((d) => d[groupBy]))];

  const traces = groups.map((g, i) => {
    const rows = data.filter((d) => d[groupBy] === g).sort((a, b) => (a.date < b.date ? -1 : 1));
    return {
      type: "scatter",
      mode: "lines+markers",
      name: labels[g] || g,
      x: rows.map((r) => r.date),
      y: rows.map((r) => r.value),
      line: { color: PALETTE[i % PALETTE.length], width: 2.5 },
      marker: { size: 5, color: PALETTE[i % PALETTE.length] },
      hovertemplate: `<b>${labels[g] || g}</b><br>%{x|%Y}: <b>%{y:.1f}</b> ${unit}<extra></extra>`,
    };
  });

  const values = data.map((d) => d.value).filter((v) => Number.isFinite(v));
  const xs = data.map((d) => d.date).sort();
  const yMin = Math.min(...values);
  const yMax = Math.max(...values);
  const pad = (yMax - yMin) * 0.08 || 1;
  const markerY = yMax + pad * 0.6;
  const layout = baseLayout(opts);
  layout.height = height;
  layout.shapes = [];

  const lastX = xs[xs.length - 1];
  const visibleEvents = events.filter((e) => e.start_date >= xs[0] && e.start_date <= lastX);
  for (const grade of ["A", "B", "C"]) {
    const evs = visibleEvents.filter((e) => e.grade === grade);
    if (!evs.length) continue;
    const colors = evs.map(() => EVENT_COLOR);
    traces.push({
      type: "scatter",
      mode: "markers",
      name: GRADE_LABEL[lang][grade],
      x: evs.map((e) => e.start_date),
      y: evs.map(() => markerY),
      marker: { symbol: GRADE_SYMBOL[grade], size: 13, color: colors, line: { width: 2, color: colors } },
      text: evs.map(
        (e) =>
          `<b>${e[`title_${lang}`] || e.title_pt}</b><br>` +
          `${t.scope}: ${SCOPE_LABEL[lang][e.scope] || e.scope} · ${GRADE_LABEL[lang][grade]}<br>` +
          `${e.start_date}${e.end_date ? " → " + e.end_date : ""}<br>` +
          `${t.source}: ${(e.primary_source_url || "").replace(/^https?:\/\//, "").slice(0, 60)}`
      ),
      hovertemplate: "%{text}<extra></extra>",
    });
  }
  for (const e of visibleEvents) {
    const color = EVENT_COLOR;
    const end = e.end_date ? (e.end_date <= lastX ? e.end_date : lastX) : null;
    layout.shapes.push(
      end
        ? { type: "rect", xref: "x", yref: "paper", x0: e.start_date, x1: end, y0: 0, y1: 1, fillcolor: color, opacity: 0.08, line: { width: 0 }, layer: "below" }
        : { type: "line", xref: "x", yref: "paper", x0: e.start_date, x1: e.start_date, y0: 0, y1: 1, line: { color, width: 1.5, dash: "dot" }, layer: "below" }
    );
  }

  layout.yaxis.range = [yMin - pad, markerY + pad * 0.5];
  layout.xaxis.rangeselector = {
    buttons: [
      { count: 10, label: `10${t.year}`, step: "year", stepmode: "backward" },
      { count: 30, label: `30${t.year}`, step: "year", stepmode: "backward" },
      { step: "all", label: t.all },
    ],
    x: 0,
    y: 1.04,
    bgcolor: "#f1f5f9",
    activecolor: "#99f6e4",
    font: { size: 12 },
  };
  layout.margin.t = 48;

  return mount(Plotly, traces, layout, baseConfig("chart"), t.hint);
}

/**
 * Sorted lollipop ranking: one dot per category, with the axis cropped to the data range
 * (a bar starting at 0 would make values in the 78-82 band look identical).
 */
export function ranking(Plotly, data, opts = {}) {
  const { lang = "pt", height = 360, highlight = null } = opts;
  const t = TEXT[lang];
  const unit = opts.unit || (data[0] && data[0].unit) || "";
  const rows = [...data].sort((a, b) => a.value - b.value);
  const lo = Math.floor(Math.min(...rows.map((r) => r.value)) - 1);
  const hi = Math.ceil(Math.max(...rows.map((r) => r.value)) + 1);

  const trace = {
    type: "scatter",
    mode: "markers+text",
    x: rows.map((r) => r.value),
    y: rows.map((r) => r.region),
    text: rows.map((r) => r.value.toFixed(1)),
    textposition: "middle right",
    textfont: { size: 12, color: "#475569" },
    marker: { size: 13, color: rows.map((r) => (r.region === highlight ? "#d97706" : "#0f766e")) },
    error_x: { type: "data", symmetric: false, array: rows.map(() => 0), arrayminus: rows.map((r) => r.value - lo), thickness: 2, width: 0, color: "#cbd5e1" },
    hovertemplate: `<b>%{y}</b><br>%{x:.2f} ${unit}<extra></extra>`,
    showlegend: false,
  };
  const layout = baseLayout({ ...opts, yTitle: "" });
  layout.height = height;
  layout.margin.l = 8;
  layout.xaxis = { range: [lo, hi + 0.6], title: { text: opts.xTitle || unit }, gridcolor: "#e5e7eb", zeroline: false, automargin: true };
  layout.yaxis = { automargin: true, categoryorder: "array", categoryarray: rows.map((r) => r.region), showgrid: false };
  layout.showlegend = false;
  return mount(Plotly, [trace], layout, baseConfig("ranking"), t.hintShort);
}

/** Build a simple HTML <table> for an accessible "see the data" fallback below a chart. */
export function dataTable(data, columns) {
  const table = document.createElement("table");
  table.className = "accessible-data";
  const headRow = table.createTHead().insertRow();
  for (const col of columns) {
    const th = document.createElement("th");
    th.textContent = col;
    headRow.appendChild(th);
  }
  const tbody = table.createTBody();
  for (const row of data) {
    const tr = tbody.insertRow();
    for (const col of columns) tr.insertCell().textContent = row[col];
  }
  return table;
}
