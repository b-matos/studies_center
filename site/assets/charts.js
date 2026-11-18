// Shared chart builders for study pages, imported from OJS cells as a local ES module:
//   import {timeSeries, ranking, groupedBars, smallMultiples} from "../../assets/charts.js"
// Plotly is passed in from the calling cell (Plotly = require("plotly.js-dist-min@2.35.2")),
// since this plain module cannot use OJS's own module resolution.
//
// Every chart gets: hover tooltips, drag-to-zoom + pan, double-click to reset, a clickable
// legend (click hides a series), a text alternative (aria-label) and a "see the data" table; time
// series also get period shortcuts and the events overlay.
//
// Catalogue (chart kind in charts.yml -> function): line -> timeSeries, ranking -> ranking,
// grouped_bars -> groupedBars, stacked_bars -> stackedBars, stacked_area -> stackedArea,
// slope -> slope, dumbbell -> dumbbell, small_multiples -> smallMultiples, scatter -> scatter,
// heatmap -> heatmap, table -> dataTable. common/chartkinds.py decides which kinds fit a data shape.

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
  pt: { seeData: "Ver os dados", hintShort: "Arraste para fazer zoom · duplo clique repõe", all: "Tudo", year: "a", scope: "Âmbito", source: "Fonte", hint: "Arraste para fazer zoom · duplo clique repõe · clique na legenda para ocultar" },
  en: { seeData: "See the data", hintShort: "Drag to zoom · double-click to reset", all: "All", year: "y", scope: "Scope", source: "Source", hint: "Drag to zoom · double-click to reset · click the legend to hide a series" },
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

function tableColumns(data) {
  const varying = ["date", "region", "sex", "age", "indicator"].filter((c) => new Set(data.map((d) => d[c])).size > 1);
  return [...new Set(["date", ...varying, "value", "unit"])].filter((c) => data.some((d) => d[c] !== undefined && d[c] !== ""));
}

/** A closed <details> whose table is built on first open, so big series cost nothing until asked for. */
function dataDetails(data, lang) {
  const details = document.createElement("details");
  details.className = "chart-data";
  const summary = document.createElement("summary");
  summary.textContent = TEXT[lang].seeData;
  details.appendChild(summary);
  details.addEventListener("toggle", () => {
    if (details.open && !details.querySelector("table")) details.appendChild(dataTable(data.slice(0, 2000), tableColumns(data)));
  });
  return details;
}

function mount(Plotly, traces, layout, config, hint, extra = {}) {
  const wrapper = document.createElement("div");
  wrapper.className = "chart-block";
  const plot = document.createElement("div");
  plot.className = "chart-plot";
  plot.setAttribute("role", "img");
  plot.setAttribute("aria-label", extra.alt || extra.title || "");
  wrapper.appendChild(plot);
  const note = document.createElement("div");
  note.className = "chart-hint";
  note.textContent = hint;
  wrapper.appendChild(note);
  if (extra.data && extra.table !== false) wrapper.appendChild(dataDetails(extra.data, extra.lang || "pt"));
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

  return mount(Plotly, traces, layout, baseConfig("chart"), t.hint, { data, lang, alt: opts.alt, title: opts.title, table: opts.table });
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
  return mount(Plotly, [trace], layout, baseConfig("ranking"), t.hintShort, { data, lang, alt: opts.alt, title: opts.title, table: opts.table });
}


// ---- Catalogue: the other chart kinds --------------------------------------------------------
// All take (Plotly, data, opts) like timeSeries. Shared opts: groupBy (field that defines a series,
// default "region"), labels, unit, title, alt (text alternative), yTitle/xTitle, lang, height, table.

const sortByDate = (rows) => [...rows].sort((a, b) => (a.date < b.date ? -1 : 1));
const nameOf = (labels, g) => labels[g] || g;
const yearOrDate = (d) => (/-01-01$/.test(d) ? d.slice(0, 4) : d);
const unitOf = (data, opts) => opts.unit || (data[0] && data[0].unit) || "";

function groupsOf(data, groupBy) {
  return [...new Set(data.map((d) => d[groupBy]))];
}

function valuesRange(data, share = 0.08) {
  const values = data.map((d) => d.value).filter((v) => Number.isFinite(v));
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * share || 1;
  return { lo, hi, pad };
}

function barChart(Plotly, data, opts, barmode, filename) {
  const { groupBy = "region", categoryBy = "date", labels = {}, lang = "pt", height = 400 } = opts;
  const t = TEXT[lang];
  const unit = unitOf(data, opts);
  const cats = [...new Set(sortByDate(data).map((d) => d[categoryBy]))];
  const traces = groupsOf(data, groupBy).map((g, i) => ({
    type: "bar",
    name: nameOf(labels, g),
    x: cats.map((c) => (categoryBy === "date" ? yearOrDate(c) : c)),
    y: cats.map((c) => {
      const row = data.find((d) => d[groupBy] === g && d[categoryBy] === c);
      return row ? row.value : null;
    }),
    marker: { color: PALETTE[i % PALETTE.length] },
    hovertemplate: `<b>${nameOf(labels, g)}</b><br>%{x}: <b>%{y:.1f}</b> ${unit}<extra></extra>`,
  }));
  const layout = baseLayout(opts);
  layout.height = height;
  layout.barmode = barmode;
  layout.yaxis.rangemode = "tozero"; // bars encode length from zero: never crop the axis
  layout.xaxis.type = "category";
  return mount(Plotly, traces, layout, baseConfig(filename), t.hintShort, { data, lang, alt: opts.alt, title: opts.title, table: opts.table });
}

/** Side-by-side bars: a few categories (dates or regions) compared across a few series. Axis starts at 0. */
export function groupedBars(Plotly, data, opts = {}) {
  return barChart(Plotly, data, opts, "group", "grouped-bars");
}

/** Stacked bars: parts of a whole (shares) per category. Only for data declared `composition: true`. */
export function stackedBars(Plotly, data, opts = {}) {
  return barChart(Plotly, data, opts, "stack", "stacked-bars");
}

/** Stacked area: how a whole is split over time. Only for data declared `composition: true`. */
export function stackedArea(Plotly, data, opts = {}) {
  const { groupBy = "region", labels = {}, lang = "pt", height = 400 } = opts;
  const t = TEXT[lang];
  const unit = unitOf(data, opts);
  const traces = groupsOf(data, groupBy).map((g, i) => {
    const rows = sortByDate(data.filter((d) => d[groupBy] === g));
    return {
      type: "scatter",
      mode: "lines",
      stackgroup: "one",
      name: nameOf(labels, g),
      x: rows.map((r) => r.date),
      y: rows.map((r) => r.value),
      line: { color: PALETTE[i % PALETTE.length], width: 1 },
      fillcolor: PALETTE[i % PALETTE.length] + "cc",
      hovertemplate: `<b>${nameOf(labels, g)}</b><br>%{x|%Y}: <b>%{y:.1f}</b> ${unit}<extra></extra>`,
    };
  });
  const layout = baseLayout(opts);
  layout.height = height;
  layout.yaxis.rangemode = "tozero";
  return mount(Plotly, traces, layout, baseConfig("stacked-area"), t.hintShort, { data, lang, alt: opts.alt, title: opts.title, table: opts.table });
}

/** Before and after: one line per series joining two dates (opts.from / opts.to, default first and last). */
export function slope(Plotly, data, opts = {}) {
  const { groupBy = "region", labels = {}, lang = "pt", height = 420 } = opts;
  const t = TEXT[lang];
  const unit = unitOf(data, opts);
  const dates = [...new Set(data.map((d) => d.date))].sort();
  const from = opts.from || dates[0];
  const to = opts.to || dates[dates.length - 1];
  const traces = [];
  groupsOf(data, groupBy).forEach((g, i) => {
    const a = data.find((d) => d[groupBy] === g && d.date === from);
    const b = data.find((d) => d[groupBy] === g && d.date === to);
    if (!a || !b) return;
    traces.push({
      type: "scatter",
      mode: "lines+markers+text",
      name: nameOf(labels, g),
      x: [yearOrDate(from), yearOrDate(to)],
      y: [a.value, b.value],
      text: [a.value.toFixed(1), `${b.value.toFixed(1)}  ${nameOf(labels, g)}`],
      textposition: ["middle left", "middle right"],
      line: { color: PALETTE[i % PALETTE.length], width: 2.5 },
      marker: { size: 8, color: PALETTE[i % PALETTE.length] },
      hovertemplate: `<b>${nameOf(labels, g)}</b><br>%{x}: <b>%{y:.1f}</b> ${unit}<extra></extra>`,
    });
  });
  const { lo, hi, pad } = valuesRange(data);
  const layout = baseLayout(opts);
  layout.height = height;
  layout.showlegend = false;
  layout.margin.l = 72;
  layout.margin.r = 160;
  layout.xaxis = { type: "category", showgrid: false, linecolor: "#cbd5e1", automargin: true };
  layout.yaxis.range = [lo - pad, hi + pad];
  return mount(Plotly, traces, layout, baseConfig("slope"), t.hintShort, { data, lang, alt: opts.alt, title: opts.title, table: opts.table });
}

/** Two dates per category on a horizontal axis, joined by a line (many regions; sorted by the later value). */
export function dumbbell(Plotly, data, opts = {}) {
  const { groupBy = "region", labels = {}, lang = "pt", height = 0 } = opts;
  const t = TEXT[lang];
  const unit = unitOf(data, opts);
  const dates = [...new Set(data.map((d) => d.date))].sort();
  const from = opts.from || dates[0];
  const to = opts.to || dates[dates.length - 1];
  const rows = groupsOf(data, groupBy)
    .map((g) => ({ g, a: data.find((d) => d[groupBy] === g && d.date === from), b: data.find((d) => d[groupBy] === g && d.date === to) }))
    .filter((r) => r.a && r.b)
    .sort((x, y) => x.b.value - y.b.value);
  const names = rows.map((r) => nameOf(labels, r.g));
  const marker = (key, color, label) => ({
    type: "scatter",
    mode: "markers",
    name: label,
    x: rows.map((r) => r[key].value),
    y: names,
    marker: { size: 11, color },
    hovertemplate: `<b>%{y}</b><br>${label}: <b>%{x:.1f}</b> ${unit}<extra></extra>`,
  });
  const lines = rows.map((r, i) => ({
    type: "scatter",
    mode: "lines",
    x: [r.a.value, r.b.value],
    y: [names[i], names[i]],
    line: { color: "#cbd5e1", width: 3 },
    hoverinfo: "skip",
    showlegend: false,
  }));
  const layout = baseLayout({ ...opts, yTitle: "" });
  layout.height = height || Math.max(280, 26 * rows.length + 110);
  layout.margin.l = 8;
  layout.xaxis = { title: { text: opts.xTitle || unit }, gridcolor: "#e5e7eb", zeroline: false, automargin: true };
  layout.yaxis = { automargin: true, categoryorder: "array", categoryarray: names, showgrid: false };
  return mount(Plotly, [...lines, marker("a", "#94a3b8", yearOrDate(from)), marker("b", "#0f766e", yearOrDate(to))], layout, baseConfig("dumbbell"), t.hintShort, { data, lang, alt: opts.alt, title: opts.title, table: opts.table });
}

/** One small panel per series, same time axis (and, by default, the same y range) so shapes compare fairly. */
export function smallMultiples(Plotly, data, opts = {}) {
  const { groupBy = "region", labels = {}, lang = "pt", sharedY = true } = opts;
  const t = TEXT[lang];
  const unit = unitOf(data, opts);
  const groups = groupsOf(data, groupBy);
  const n = groups.length;
  const cols = opts.cols || (n <= 4 ? 2 : 3);
  const nRows = Math.ceil(n / cols);
  const gapX = 0.07;
  const gapY = 0.16;
  const w = (1 - gapX * (cols - 1)) / cols;
  const h = (1 - gapY * (nRows - 1)) / nRows;
  const { lo, hi, pad } = valuesRange(data);
  const layout = baseLayout({ ...opts, yTitle: "" });
  layout.height = opts.height || 170 * nRows + 90;
  layout.showlegend = false;
  layout.annotations = [];
  delete layout.xaxis;
  delete layout.yaxis;
  const id = (k) => (k === 1 ? "" : String(k));
  const traces = groups.map((g, i) => {
    const k = i + 1;
    const r = Math.floor(i / cols);
    const c = i % cols;
    const x0 = c * (w + gapX);
    const y1 = 1 - r * (h + gapY);
    layout[`xaxis${id(k)}`] = { domain: [x0, x0 + w], anchor: `y${id(k)}`, showgrid: false, linecolor: "#cbd5e1", ticks: "outside", tickcolor: "#cbd5e1" };
    layout[`yaxis${id(k)}`] = { domain: [y1 - h, y1], anchor: `x${id(k)}`, gridcolor: "#e5e7eb", zeroline: false, ...(sharedY ? { range: [lo - pad, hi + pad] } : {}) };
    layout.annotations.push({ text: `<b>${nameOf(labels, g)}</b>`, xref: "paper", yref: "paper", x: x0, y: y1, xanchor: "left", yanchor: "bottom", showarrow: false, font: { size: 12 } });
    const rows = sortByDate(data.filter((d) => d[groupBy] === g));
    return {
      type: "scatter",
      mode: "lines",
      x: rows.map((q) => q.date),
      y: rows.map((q) => q.value),
      xaxis: `x${id(k)}`,
      yaxis: `y${id(k)}`,
      line: { color: PALETTE[i % PALETTE.length], width: 2.2 },
      hovertemplate: `<b>${nameOf(labels, g)}</b><br>%{x|%Y}: <b>%{y:.1f}</b> ${unit}<extra></extra>`,
    };
  });
  return mount(Plotly, traces, layout, baseConfig("small-multiples"), t.hintShort, { data, lang, alt: opts.alt, title: opts.title, table: opts.table });
}

/**
 * Relation between two indicators: one dot per (region, date) where both exist, coloured by year.
 * opts.xIndicator / opts.yIndicator pick the two (default: the first two `indicator` values, sorted).
 * A scatter shows association, never cause; say so in the text next to it.
 */
export function scatter(Plotly, data, opts = {}) {
  const { labels = {}, lang = "pt", height = 440 } = opts;
  const t = TEXT[lang];
  const indicators = [...new Set(data.map((d) => d.indicator))].sort();
  const xi = opts.xIndicator || indicators[0];
  const yi = opts.yIndicator || indicators[1];
  const key = (d) => `${d.region}|${d.date}`;
  const xs = new Map(data.filter((d) => d.indicator === xi).map((d) => [key(d), d]));
  const pairs = data.filter((d) => d.indicator === yi && xs.has(key(d))).map((d) => ({ x: xs.get(key(d)), y: d }));
  const trace = {
    type: "scatter",
    mode: "markers",
    x: pairs.map((p) => p.x.value),
    y: pairs.map((p) => p.y.value),
    text: pairs.map((p) => `${p.y.region} · ${yearOrDate(p.y.date)}`),
    marker: {
      size: 9,
      color: pairs.map((p) => Number(p.y.date.slice(0, 4))),
      colorscale: [[0, "#99f6e4"], [1, "#134e4a"]],
      colorbar: { title: { text: lang === "pt" ? "Ano" : "Year" }, thickness: 12 },
      line: { width: 1, color: "#ffffff" },
    },
    hovertemplate: `<b>%{text}</b><br>${nameOf(labels, xi)}: %{x:.1f}<br>${nameOf(labels, yi)}: %{y:.1f}<extra></extra>`,
    showlegend: false,
  };
  const layout = baseLayout({ ...opts, yTitle: opts.yTitle || nameOf(labels, yi) });
  layout.height = height;
  layout.xaxis = { title: { text: opts.xTitle || nameOf(labels, xi) }, gridcolor: "#e5e7eb", zeroline: false, automargin: true };
  return mount(Plotly, [trace], layout, baseConfig("scatter"), t.hintShort, { data, lang, alt: opts.alt, title: opts.title, table: opts.table });
}

/** Year by region grid with one sequential colour. Pass one indicator (filter sex and age first). */
export function heatmap(Plotly, data, opts = {}) {
  const { groupBy = "region", labels = {}, lang = "pt" } = opts;
  const t = TEXT[lang];
  const unit = unitOf(data, opts);
  const dates = [...new Set(data.map((d) => d.date))].sort();
  const mean = (g) => {
    const v = data.filter((d) => d[groupBy] === g).map((d) => d.value);
    return v.reduce((a, b) => a + b, 0) / v.length;
  };
  const groups = groupsOf(data, groupBy).sort((a, b) => mean(b) - mean(a));
  const z = groups.map((g) => dates.map((d) => {
    const row = data.find((q) => q[groupBy] === g && q.date === d);
    return row ? row.value : null;
  }));
  const trace = {
    type: "heatmap",
    x: dates.map(yearOrDate),
    y: groups.map((g) => nameOf(labels, g)),
    z,
    colorscale: [[0, "#f0fdfa"], [1, "#0f766e"]],
    colorbar: { title: { text: unit }, thickness: 12 },
    hovertemplate: `<b>%{y}</b><br>%{x}: <b>%{z:.1f}</b> ${unit}<extra></extra>`,
    xgap: 1,
    ygap: 1,
  };
  const layout = baseLayout({ ...opts, yTitle: "" });
  layout.height = opts.height || Math.max(280, 28 * groups.length + 110);
  layout.margin.l = 8;
  layout.xaxis = { type: "category", automargin: true, side: "bottom" };
  layout.yaxis = { automargin: true, autorange: "reversed" };
  return mount(Plotly, [trace], layout, baseConfig("heatmap"), t.hintShort, { data, lang, alt: opts.alt, title: opts.title, table: opts.table });
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
