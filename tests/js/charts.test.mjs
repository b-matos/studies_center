// Structure tests for the chart catalogue, with a stub DOM and a stub Plotly (no browser needed).
// Run by tests/test_charts_catalogue.py; also runnable alone: node tests/js/charts.test.mjs
import assert from "node:assert/strict";

const el = (tag) => ({
  tag, children: [], attrs: {}, className: "", textContent: "",
  appendChild(c) { this.children.push(c); return c; },
  setAttribute(k, v) { this.attrs[k] = v; },
  addEventListener() {},
  querySelector() { return null; },
});
globalThis.document = { body: {}, createElement: el };
globalThis.getComputedStyle = () => ({ fontFamily: "Inter" });

const calls = [];
const Plotly = { newPlot(plot, traces, layout, config) { calls.push({ plot, traces, layout, config }); }, Plots: { resize() {} } };
const charts = await import("../../site/assets/charts.js");

const years = [2000, 2005, 2010, 2015, 2020];
const row = (region, year, value, extra = {}) => ({ date: `${year}-01-01`, region, sex: "T", age: "", indicator: "x", value, unit: "%", ...extra });
const regions = ["Norte", "Centro", "Lisboa", "Alentejo"];
const data = regions.flatMap((r, i) => years.map((y, j) => row(r, y, 10 + i * 3 + j)));
const last = () => calls[calls.length - 1];

function check(name, fn, opts = {}) {
  calls.length = 0;
  const wrapper = fn(Plotly, data, { title: "T", alt: "alt text", ...opts });
  assert.equal(calls.length, 1, `${name}: one Plotly.newPlot`);
  assert.ok(last().traces.length > 0, `${name}: has traces`);
  const [plot, note, details] = wrapper.children;
  assert.equal(plot.attrs.role, "img", `${name}: role=img`);
  assert.equal(plot.attrs["aria-label"], "alt text", `${name}: aria-label`);
  assert.equal(details.tag, "details", `${name}: "see the data" fallback`);
  assert.equal(wrapper.children.length, 3, `${name}: plot, hint, data`);
  return last();
}

for (const [name, fn] of Object.entries({
  timeSeries: charts.timeSeries, ranking: charts.ranking, groupedBars: charts.groupedBars, stackedBars: charts.stackedBars,
  stackedArea: charts.stackedArea, slope: charts.slope, dumbbell: charts.dumbbell, smallMultiples: charts.smallMultiples, heatmap: charts.heatmap,
})) check(name, fn, name === "ranking" ? {} : {});

let c = check("groupedBars", charts.groupedBars);
assert.equal(c.layout.barmode, "group");
assert.equal(c.layout.yaxis.rangemode, "tozero", "bars start at zero");
assert.equal(c.traces.length, regions.length);

c = check("stackedBars", charts.stackedBars);
assert.equal(c.layout.barmode, "stack");

c = check("stackedArea", charts.stackedArea);
assert.ok(c.traces.every((t) => t.stackgroup === "one"));

c = check("slope", charts.slope);
assert.equal(c.traces.length, regions.length);
assert.deepEqual(c.traces[0].x, ["2000", "2020"], "first and last date by default");
c = check("slope", charts.slope, { from: "2005-01-01", to: "2015-01-01" });
assert.deepEqual(c.traces[0].x, ["2005", "2015"]);

c = check("dumbbell", charts.dumbbell);
assert.equal(c.traces.length, regions.length + 2, "one joining line per category plus two marker traces");
assert.deepEqual(c.layout.yaxis.categoryarray.length, regions.length);

c = check("smallMultiples", charts.smallMultiples);
assert.equal(c.traces.length, regions.length);
assert.ok(c.layout.xaxis && c.layout.xaxis2 && c.layout.yaxis4, "one axis pair per panel, the first one unsuffixed");
assert.equal(c.layout.xaxis.domain[0], 0);
assert.equal(c.layout.xaxis.anchor, "y");
assert.equal(c.layout.annotations.length, regions.length, "a title per panel");
assert.equal(c.traces[1].xaxis, "x2");
assert.deepEqual(c.layout.yaxis.range, c.layout.yaxis3.range, "shared y range by default");

c = check("heatmap", charts.heatmap);
assert.equal(c.traces[0].z.length, regions.length);
assert.equal(c.traces[0].z[0].length, years.length);

// scatter pairs two indicators on (region, date) and ignores unmatched points
const two = regions.flatMap((r, i) => years.flatMap((y, j) => [
  row(r, y, 10 + j + i, { indicator: "a" }),
  ...(j < 4 ? [row(r, y, 50 + j * 2 - i, { indicator: "b" })] : []),
]));
calls.length = 0;
charts.scatter(Plotly, two, { alt: "s" });
assert.equal(last().traces[0].x.length, regions.length * 4, "only dates where both indicators exist");
assert.equal(last().traces[0].marker.color[0], 2000, "coloured by year");

// choropleth: needs boundaries and region codes, shows only the chosen date, greys the units without data
const geojson = { type: "FeatureCollection", features: [
  { properties: { nuts_id: "PT11", name: "Norte", shifted: false } },
  { properties: { nuts_id: "PT19", name: "Centro (PT)", shifted: false } },
  { properties: { nuts_id: "PT20", name: "Região Autónoma dos Açores", shifted: true } },
] };
const coded = [
  { ...row("Norte", 2020, 10), region_code: "PT11" }, { ...row("Centro", 2020, 20), region_code: "PT19" },
  { ...row("Norte", 2015, 99), region_code: "PT11" },
];
calls.length = 0;
const mapWrapper = charts.choropleth(Plotly, coded, { geojson, alt: "map", lang: "en" });
assert.equal(calls.length, 1);
const [grey, shown] = last().traces;
assert.deepEqual(grey.locations, ["PT11", "PT19", "PT20"], "every unit gets a grey base");
assert.deepEqual(shown.locations, ["PT11", "PT19"], "latest date only, units with data only");
assert.deepEqual(shown.z, [10, 20]);
assert.deepEqual(shown.text, ["Norte", "Centro"], "names come from the boundaries, without the (PT) suffix");
assert.equal(last().layout.geo.fitbounds, "locations");
const hint = mapWrapper.children[1].textContent;
assert.ok(hint.includes("EuroGeographics") && hint.includes("Azores") && hint.includes("1 no data"), hint);
calls.length = 0;
charts.choropleth(Plotly, coded, { geojson, date: "2015-01-01" });
assert.deepEqual(last().traces[1].z, [99], "opts.date picks the date");
assert.throws(() => charts.choropleth(Plotly, coded, {}), /geojson/);

// timeSeries and ranking keep working with the shared shell
calls.length = 0;
charts.timeSeries(Plotly, data, { events: [] });
assert.equal(last().traces.length, regions.length);
console.log("charts catalogue: ok");
