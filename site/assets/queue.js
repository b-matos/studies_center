// Local study queue page: add topics to a backlog, choose what runs next, follow progress
// phase by phase, and see token usage and cost per study. Talks to the local FastAPI server
// (server/app.py); it does nothing useful on a static host, so it says so instead.
(function () {
  const script = document.currentScript;
  const lang = script.dataset.lang === "en" ? "en" : "pt";
  const T = {
    pt: {
      add: "Adicionar à fila", placeholder: "Tema do estudo, por exemplo: saúde em Portugal",
      run: "Executar", runNext: "Executar a seguir", resume: "Retomar", remove: "Remover", queued: "Na fila",
      flagged: "A seguir", running: "A correr", done: "Concluído", failed: "Falhou", interrupted: "Interrompido", needs_you: "Precisa de ti",
      empty: "A fila está vazia. Adiciona um tema acima.", noRun: "Nada a correr neste momento.",
      plan: "Plano: 5 h", week: "7 dias", resets: "renova às", limit: "Limite atingido",
      phases: ["Plano", "Fontes", "Extração", "Análise", "Eventos", "Redação", "Verificação", "Publicação"],
      tokens: "tokens", cost: "custo", phase: "Fase", study: "Estudo", total: "Total", noUsage: "Ainda sem consumo registado.",
      estimate: "Custo por fase é uma estimativa; o total do estudo é exato (equivalente ao preço de lista da API).",
      offline: "Sem ligação ao servidor local. Inicia-o com: uv run python -m server.app", doing: "A fazer",
    },
    en: {
      add: "Add to queue", placeholder: "Study topic, for example: health in Portugal",
      run: "Run", runNext: "Run next", resume: "Resume", remove: "Remove", queued: "Queued",
      flagged: "Up next", running: "Running", done: "Done", failed: "Failed", interrupted: "Interrupted", needs_you: "Needs you",
      empty: "The queue is empty. Add a topic above.", noRun: "Nothing is running right now.",
      plan: "Plan: 5 h", week: "7 days", resets: "resets at", limit: "Limit reached",
      phases: ["Plan", "Sources", "Extraction", "Analysis", "Events", "Writing", "Verification", "Publication"],
      tokens: "tokens", cost: "cost", phase: "Phase", study: "Study", total: "Total", noUsage: "No usage recorded yet.",
      estimate: "Cost per phase is an estimate; the study total is exact (API list-price equivalent).",
      offline: "No connection to the local server. Start it with: uv run python -m server.app", doing: "Doing",
    },
  }[lang];

  const $ = (id) => document.getElementById(id);
  const fmt = (n) => Number(n || 0).toLocaleString(lang === "pt" ? "pt-PT" : "en-GB");
  const usd = (n) => "$" + Number(n || 0).toFixed(2);
  const tokensOf = (r) => (r.input_tokens || 0) + (r.cache_read_tokens || 0) + (r.cache_creation_tokens || 0) + (r.output_tokens || 0);
  const clock = (epoch) => new Date(epoch * 1000).toLocaleTimeString(lang === "pt" ? "pt-PT" : "en-GB", { hour: "2-digit", minute: "2-digit" });

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const c of children.flat()) node.append(c instanceof Node ? c : document.createTextNode(String(c)));
    return node;
  }

  async function api(path, method = "GET", body) {
    const resp = await fetch(path, {
      method, headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined,
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
    return data;
  }

  let items = [];

  function renderQueue() {
    const list = $("q-list");
    list.replaceChildren();
    if (!items.length) list.append(el("p", { class: "q-empty" }, T.empty));
    const busy = items.some((i) => i.status === "running");
    for (const item of items) {
      const status = item.run_next && item.status !== "running" ? "flagged" : item.status;
      const meta = [];
      if (item.slug) meta.push(item.slug);
      if (item.tokens) meta.push(`${fmt(item.tokens)} ${T.tokens} · ${usd(item.cost_usd)}`);
      if (item.status === "interrupted" && item.resets_at) meta.push(`${T.limit} · ${T.resets} ${clock(item.resets_at)}`);
      const canRun = ["queued", "interrupted", "failed", "needs_you"].includes(item.status) && !item.run_next;
      const label = item.status === "queued" ? (busy ? T.runNext : T.run) : (busy ? T.runNext : T.resume);
      list.append(el("div", { class: `q-item q-${status}` },
        el("div", { class: "q-main" }, el("strong", {}, item.topic), el("span", { class: "q-meta" }, meta.join(" · ")),
          item.note ? el("span", { class: "q-note" }, item.note) : ""),
        el("span", { class: `badge-estado q-badge-${status}` }, T[status] || status),
        canRun ? el("button", { onclick: () => act(() => api(`/api/queue/${item.id}/run`, "POST")) }, label) : "",
        item.status !== "running" ? el("button", { class: "q-secondary", onclick: () => act(() => api(`/api/queue/${item.id}`, "DELETE")) }, T.remove) : ""));
    }
    if (!busy) renderProgress(null);
  }

  function renderProgress(p) {
    const box = $("q-progress");
    box.replaceChildren();
    if (!p) { box.append(el("p", { class: "q-empty" }, T.noRun)); return; }
    box.append(el("p", { class: "q-slug" }, p.slug, el("span", { class: "q-meta" }, ` · ${fmt(p.tokens)} ${T.tokens}`)));
    const rows = el("ol", { class: "q-phases" });
    for (const ph of p.phases) {
      const mark = ph.status === "completed" ? "✓" : ph.status === "in_progress" ? "●" : ph.status === "blocked" ? "✕" : "○";
      const count = ph.total && ph.status !== "completed" ? ` ${ph.done}/${ph.total}` : "";
      rows.append(el("li", { class: `q-phase q-ph-${ph.status}` }, el("span", { class: "q-mark" }, mark), T.phases[ph.n - 1], count));
    }
    box.append(rows, el("p", { class: "q-activity", id: "q-activity" }));
  }

  function renderPlan(e) {
    const pct = (v) => (v == null ? "–" : Math.round(v * 100) + "%");
    $("q-plan").textContent = `${T.plan} ${pct(e.five_hour)} · ${T.week} ${pct(e.seven_day)}` + (e.resets_at ? ` · ${T.resets} ${clock(e.resets_at)}` : "");
  }

  function renderUsage(studies) {
    const box = $("q-usage");
    box.replaceChildren();
    if (!studies.length) { box.append(el("p", { class: "q-empty" }, T.noUsage)); return; }
    const table = el("table", { class: "q-table" },
      el("thead", {}, el("tr", {}, el("th", {}, T.study), el("th", {}, T.tokens), el("th", {}, T.cost))));
    const body = el("tbody");
    for (const s of studies) {
      body.append(el("tr", { class: "q-study-row" }, el("td", {}, s.slug), el("td", {}, fmt(tokensOf(s))), el("td", {}, usd(s.cost_usd))));
      for (const p of s.phases) {
        body.append(el("tr", { class: "q-phase-row" }, el("td", {}, `${p.phase} · ${isNaN(p.phase) ? p.name : T.phases[p.phase - 1]}`), el("td", {}, fmt(tokensOf(p))), el("td", {}, "~" + usd(p.cost_usd))));
      }
    }
    table.append(body);
    box.append(table, el("p", { class: "q-meta" }, T.estimate));
  }

  async function act(fn) {
    $("q-error").textContent = "";
    try { await fn(); } catch (e) { $("q-error").textContent = e.message; }
  }

  function handle(e) {
    if (e.type === "queue") { items = e.items; renderQueue(); }
    else if (e.type === "progress") renderProgress(e);
    else if (e.type === "activity") { const a = $("q-activity"); if (a) a.textContent = `${T.doing}: ${e.text}`; }
    else if (e.type === "plan_usage") renderPlan(e);
    else if (e.type === "usage") renderUsage(e.studies);
    else if (e.type === "limit") $("q-error").textContent = e.text;
    else if (e.type === "error") $("q-error").textContent = e.text;
  }

  async function init() {
    $("q-topic").placeholder = T.placeholder;
    $("q-add").textContent = T.add;
    $("q-form").addEventListener("submit", (ev) => {
      ev.preventDefault();
      act(async () => { await api("/api/queue", "POST", { topic: $("q-topic").value }); $("q-topic").value = ""; });
    });
    try {
      items = (await api("/api/queue")).items;
      renderQueue();
      renderUsage((await api("/api/usage")).studies);
      const stream = new EventSource("/api/events");
      stream.onmessage = (m) => handle(JSON.parse(m.data));
    } catch (e) {
      $("q-error").textContent = T.offline;
    }
  }
  init();
})();
