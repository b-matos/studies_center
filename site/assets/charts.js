// Shared chart builder for study pages, imported from OJS cells as a local ES module:
//   import {serieComEventos} from "../../assets/charts.js"
// Plot and Inputs are passed in from the calling cell (imported there via "npm:@observablehq/plot"),
// since this plain module cannot use OJS's "npm:" import resolution itself.

const AMBITO_COLOR = { PT: "#0a5c6b", UE: "#8a6d00", Mundo: "#6b6b6b" };
const GRAU_LABEL = {
  A: "contribuiu para / contributed to",
  B: "pode ter contribuído / may have contributed to",
  C: "coincidiu com / coincided with",
};

/**
 * Render a time series with an events timeline overlay.
 *
 * @param {object} Plot - the Observable Plot module, imported by the caller.
 * @param {Array<object>} data - canonical long rows: {data, regiao, sexo, idade, indicador, valor, unidade}.
 * @param {Array<object>} eventos - event rows to overlay, each optionally carrying a `grau` (A|B|C)
 *   field set by the caller after joining with ligacoes_eventos.csv for the breaks shown in this chart.
 * @param {object} opts
 */
export function serieComEventos(Plot, data, eventos = [], opts = {}) {
  const {
    width = 680,
    height = 380,
    xLabel = "Ano",
    yLabel = "Valor",
    colorField = null,
  } = opts;

  const marks = [
    Plot.ruleY([0]),
    Plot.lineY(data, {
      x: "data",
      y: "valor",
      stroke: colorField || "#0a5c6b",
      strokeWidth: 2,
    }),
    Plot.dot(data, { x: "data", y: "valor", fill: colorField || "#0a5c6b", r: 2 }),
  ];

  if (eventos.length) {
    marks.push(
      Plot.ruleX(eventos, {
        x: "data_inicio",
        stroke: (d) => AMBITO_COLOR[d.ambito] || "#999",
        strokeOpacity: 0.55,
        strokeDasharray: (d) => (d.grau === "C" ? "2,2" : null),
      })
    );
    marks.push(
      Plot.tip(
        eventos,
        Plot.pointerX({
          x: "data_inicio",
          title: (d) =>
            `${d.titulo_pt || d.titulo_en}\n` +
            `âmbito: ${d.ambito}${d.grau ? " · grau " + d.grau + " (" + GRAU_LABEL[d.grau] + ")" : ""}\n` +
            `${d.fonte_primaria_url || ""}`,
        })
      )
    );
  }

  return Plot.plot({
    width,
    height,
    marginLeft: 50,
    x: { label: xLabel },
    y: { label: yLabel, grid: true },
    marks,
  });
}

/** Build a simple HTML <table> for the "ver dados" accessible fallback below each chart. */
export function tabelaDados(data, columns) {
  const table = document.createElement("table");
  table.className = "dados-acessiveis";
  const thead = table.createTHead();
  const headRow = thead.insertRow();
  for (const col of columns) {
    const th = document.createElement("th");
    th.textContent = col;
    headRow.appendChild(th);
  }
  const tbody = table.createTBody();
  for (const row of data) {
    const tr = tbody.insertRow();
    for (const col of columns) {
      const td = tr.insertCell();
      td.textContent = row[col];
    }
  }
  return table;
}

/** Apply the standard region/sex/age/period filters, skipping any dimension absent from the data. */
export function aplicarFiltros(data, filtros) {
  return data.filter((d) => {
    if (filtros.regiao && filtros.regiao !== "Todas" && d.regiao !== filtros.regiao) return false;
    if (filtros.sexo && filtros.sexo !== "Todos" && d.sexo !== filtros.sexo) return false;
    if (filtros.idade && filtros.idade !== "Todas" && d.idade !== filtros.idade) return false;
    if (filtros.periodo) {
      const ano = new Date(d.data).getFullYear();
      if (ano < filtros.periodo[0] || ano > filtros.periodo[1]) return false;
    }
    return true;
  });
}
