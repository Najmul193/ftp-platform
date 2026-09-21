import {
  accountRankings,
  branchAnalysis,
  dailyAnalysis,
  exceptionAnalysis,
  filterRecords,
  heatmap,
  money,
  number,
  productAnalysis,
  ratio,
  scenarioByProduct,
  simulate,
  summarize,
  unique,
} from "./analytics.js";

const state = {
  metadata: null,
  records: [],
  filters: {
    from: "",
    to: "",
    branch: "ALL",
    product: "ALL",
    type: "ALL",
    account: "",
  },
  shocks: {
    benchmarkBps: 0,
    liquidityBps: 0,
    otherBps: 0,
  },
};

const els = {
  dataMeta: document.querySelector("#dataMeta"),
  dateFrom: document.querySelector("#dateFrom"),
  dateTo: document.querySelector("#dateTo"),
  branchFilter: document.querySelector("#branchFilter"),
  productFilter: document.querySelector("#productFilter"),
  typeFilter: document.querySelector("#typeFilter"),
  accountSearch: document.querySelector("#accountSearch"),
  resetFilters: document.querySelector("#resetFilters"),
  exportCsv: document.querySelector("#exportCsv"),
  kpiGrid: document.querySelector("#kpiGrid"),
  branchBarChart: document.querySelector("#branchBarChart"),
  productDonut: document.querySelector("#productDonut"),
  branchTable: document.querySelector("#branchTable"),
  productTable: document.querySelector("#productTable"),
  trendChart: document.querySelector("#trendChart"),
  dailyTable: document.querySelector("#dailyTable"),
  accountTable: document.querySelector("#accountTable"),
  topAccounts: document.querySelector("#topAccounts"),
  bottomAccounts: document.querySelector("#bottomAccounts"),
  heatmap: document.querySelector("#heatmap"),
  exceptionKpis: document.querySelector("#exceptionKpis"),
  exceptionTable: document.querySelector("#exceptionTable"),
  recordCountBadge: document.querySelector("#recordCountBadge"),
  branchCountBadge: document.querySelector("#branchCountBadge"),
  productCountBadge: document.querySelector("#productCountBadge"),
  benchmarkShock: document.querySelector("#benchmarkShock"),
  liquidityShock: document.querySelector("#liquidityShock"),
  otherShock: document.querySelector("#otherShock"),
  benchmarkValue: document.querySelector("#benchmarkValue"),
  liquidityValue: document.querySelector("#liquidityValue"),
  otherValue: document.querySelector("#otherValue"),
  scenarioKpis: document.querySelector("#scenarioKpis"),
  scenarioTable: document.querySelector("#scenarioTable"),
  configTable: document.querySelector("#configTable"),
  controlSummary: document.querySelector("#controlSummary"),
  scatterChart: document.querySelector("#scatterChart"),
};

init();

async function init() {
  const response = await fetch("./data/ftp-results.json");
  const payload = await response.json();
  state.metadata = payload.metadata;
  state.records = payload.records;

  hydrateFilters();
  bindEvents();
  render();
}

function hydrateFilters() {
  const { dateRange } = state.metadata;
  els.dateFrom.value = dateRange.from;
  els.dateTo.value = dateRange.to;
  state.filters.from = dateRange.from;
  state.filters.to = dateRange.to;

  hydrateSelect(els.branchFilter, ["ALL", ...unique(state.records, "branch")], "All Branches");
  hydrateSelect(els.productFilter, ["ALL", ...unique(state.records, "product")], "All Products");
}

function hydrateSelect(select, values, allLabel) {
  select.innerHTML = values
    .map((value) => `<option value="${escapeAttr(value)}">${value === "ALL" ? allLabel : value}</option>`)
    .join("");
}

function bindEvents() {
  document.querySelectorAll(".nav-tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".nav-tab").forEach((tab) => tab.classList.remove("is-active"));
      document.querySelectorAll(".view").forEach((view) => view.classList.remove("is-active"));
      button.classList.add("is-active");
      document.querySelector(`#${button.dataset.view}`).classList.add("is-active");
    });
  });

  [
    [els.dateFrom, "from"],
    [els.dateTo, "to"],
    [els.branchFilter, "branch"],
    [els.productFilter, "product"],
    [els.typeFilter, "type"],
    [els.accountSearch, "account"],
  ].forEach(([element, key]) => {
    element.addEventListener("input", () => {
      state.filters[key] = element.value;
      render();
    });
  });

  els.resetFilters.addEventListener("click", () => {
    state.filters = {
      from: state.metadata.dateRange.from,
      to: state.metadata.dateRange.to,
      branch: "ALL",
      product: "ALL",
      type: "ALL",
      account: "",
    };
    els.dateFrom.value = state.filters.from;
    els.dateTo.value = state.filters.to;
    els.branchFilter.value = "ALL";
    els.productFilter.value = "ALL";
    els.typeFilter.value = "ALL";
    els.accountSearch.value = "";
    render();
  });

  els.exportCsv.addEventListener("click", () => exportCurrentCsv());

  [
    [els.benchmarkShock, "benchmarkBps", els.benchmarkValue],
    [els.liquidityShock, "liquidityBps", els.liquidityValue],
    [els.otherShock, "otherBps", els.otherValue],
  ].forEach(([input, key, output]) => {
    input.addEventListener("input", () => {
      state.shocks[key] = Number(input.value);
      output.textContent = `${input.value} bps`;
      renderScenario();
    });
  });
}

function render() {
  const records = filterRecords(state.records, state.filters);
  const summary = summarize(records);
  const branches = branchAnalysis(records);
  const products = productAnalysis(records);
  const daily = dailyAnalysis(records);
  const rankings = accountRankings(records);
  const exceptions = exceptionAnalysis(records);

  els.dataMeta.textContent = `${state.metadata.recordCount} records, ${state.metadata.dateRange.from} to ${state.metadata.dateRange.to}`;
  els.recordCountBadge.textContent = `${records.length} records`;
  els.branchCountBadge.textContent = `${summary.branches} branches`;
  els.productCountBadge.textContent = `${summary.products} products`;

  renderKpis(summary);
  renderBranchBar(branches);
  renderProductDonut(products);
  renderTables({ branches, products, daily, rankings, records, exceptions, summary });
  renderHeatmap(heatmap(records));
  renderTrend(daily);
  renderScatter(products);
  renderGovernance();
  renderScenario();
}

function renderKpis(summary) {
  els.kpiGrid.innerHTML = [
    kpi("Net FTP Profit", money(summary.netFtpProfit), "Asset plus liability FTP profit"),
    kpi("Asset FTP Profit", money(summary.assetFtpProfit), `${money(summary.assetBalance, true)} balance`),
    kpi("Liability FTP Profit", money(summary.liabilityFtpProfit), `${money(summary.liabilityBalance, true)} balance`),
    kpi("FTP / Balance", ratio(summary.ftpOnBalance), "Annualized on total balance"),
    kpi("Avg FTP Rate", ratio(summary.avgFtpRate), "Weighted by balance"),
    kpi("Avg ROI", ratio(summary.avgRoi), "Weighted by balance"),
    kpi("Negative FTP", number(summary.negativeFtpCount, 0), "Records requiring review"),
    kpi("Accounts", number(summary.accounts, 0), `${summary.days} business days`),
  ].join("");
}

function renderTables({ branches, products, daily, rankings, records, exceptions, summary }) {
  els.branchTable.innerHTML = table(
    ["Branch", "Accounts", "Asset Balance", "Liability Balance", "Asset FTP", "Liability FTP", "Net FTP", "FTP / Balance", "Negative"],
    branches.map((row) => [
      row.branch,
      number(row.accounts, 0),
      money(row.assetBalance),
      money(row.liabilityBalance),
      money(row.assetFtpProfit),
      money(row.liabilityFtpProfit),
      money(row.netFtpProfit),
      ratio(row.ftpOnBalance),
      number(row.negativeCount, 0),
    ]),
  );

  els.productTable.innerHTML = table(
    ["Product", "Type", "Balance", "FTP Profit", "Avg ROI", "Benchmark", "FTP Rate", "Profit / Balance", "Negative"],
    products.map((row) => [
      row.product,
      badge(row.type === "A" ? "Asset" : "Liability", row.type === "A" ? "asset" : "liability"),
      money(row.balance),
      money(row.ftpProfit),
      ratio(row.avgRoi),
      ratio(row.avgBenchmark),
      ratio(row.avgFtpRate),
      ratio(row.profitPerBalance),
      number(row.negativeCount, 0),
    ]),
  );

  els.dailyTable.innerHTML = table(
    ["Date", "Asset FTP", "Liability FTP", "Net FTP", "Balance", "Accounts"],
    daily.map((row) => [
      row.date,
      money(row.assetProfit),
      money(row.liabilityProfit),
      money(row.netProfit),
      money(row.balance),
      number(row.accounts, 0),
    ]),
  );

  els.accountTable.innerHTML = table(
    ["Date", "Branch", "Account", "Product", "Type", "Balance", "ROI", "FTP Rate", "FTP Profit"],
    records
      .slice()
      .sort((a, b) => Math.abs(b.ftp_profit) - Math.abs(a.ftp_profit))
      .slice(0, 80)
      .map((row) => [
        row.date,
        row.branch,
        row.account,
        row.product,
        badge(row.type === "A" ? "Asset" : "Liability", row.type === "A" ? "asset" : "liability"),
        money(row.balance),
        ratio(row.roi),
        ratio(row.ftp_rate),
        money(row.ftp_profit),
      ]),
  );

  els.topAccounts.innerHTML = sectionTable(
    "Top Accounts",
    ["Account", "Branch", "Product", "FTP Profit"],
    rankings.top.slice(0, 7).map((row) => [row.account, row.branch, row.product, money(row.ftpProfit)]),
  );
  els.bottomAccounts.innerHTML = sectionTable(
    "Bottom Accounts",
    ["Account", "Branch", "Product", "FTP Profit"],
    rankings.bottom.slice(0, 7).map((row) => [row.account, row.branch, row.product, money(row.ftpProfit)]),
  );

  els.exceptionKpis.innerHTML = [
    kpi("Exception Records", number(exceptions.length, 0), "Negative FTP or mismatch"),
    kpi("Negative FTP", number(exceptions.filter((row) => row.negativeFtp).length, 0), "Rate or income below zero"),
    kpi("Interest Mismatch", number(exceptions.filter((row) => row.interestMismatch).length, 0), "Outside tolerance"),
    kpi("Portfolio Records", number(summary.records, 0), "After active filters"),
  ].join("");

  els.exceptionTable.innerHTML = table(
    ["Date", "Branch", "Account", "Product", "Type", "FTP Rate", "FTP Profit", "Interest Variance"],
    exceptions.slice(0, 80).map((row) => [
      row.date,
      row.branch,
      row.account,
      row.product,
      badge(row.type === "A" ? "Asset" : "Liability", row.type === "A" ? "asset" : "liability"),
      ratio(row.ftp_rate),
      money(row.ftp_profit),
      money(row.interestVariance),
    ]),
  );
}

function renderBranchBar(branches) {
  const max = Math.max(...branches.map((row) => Math.abs(row.netFtpProfit)), 1);
  els.branchBarChart.innerHTML = `
    <div class="bar-list">
      ${branches
        .map((row) => {
          const width = Math.max(4, (Math.abs(row.netFtpProfit) / max) * 100);
          return `
            <div class="bar-row">
              <span>${escapeHtml(row.branch)}</span>
              <div class="bar-track"><div class="bar-fill" style="width:${width}%"></div></div>
              <strong>${money(row.netFtpProfit)}</strong>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderProductDonut(products) {
  const total = products.reduce((sum, row) => sum + Math.max(row.ftpProfit, 0), 0) || 1;
  let offset = 0;
  const segments = products
    .map((row, index) => {
      const pct = Math.max(row.ftpProfit, 0) / total;
      const dash = `${pct * 100} ${100 - pct * 100}`;
      const segment = `<circle class="donut-segment c${index}" r="15.9155" cx="18" cy="18" stroke-dasharray="${dash}" stroke-dashoffset="${-offset}" />`;
      offset += pct * 100;
      return segment;
    })
    .join("");
  els.productDonut.innerHTML = `
    <div class="donut-wrap">
      <svg viewBox="0 0 36 36" class="donut" role="img" aria-label="Product contribution donut">
        <circle class="donut-bg" r="15.9155" cx="18" cy="18"></circle>
        ${segments}
      </svg>
      <div class="legend">
        ${products
          .map((row, index) => `<div><span class="legend-key c${index}"></span>${escapeHtml(row.product)} <strong>${money(row.ftpProfit)}</strong></div>`)
          .join("")}
      </div>
    </div>
  `;
}

function renderTrend(daily) {
  if (!daily.length) {
    els.trendChart.innerHTML = emptyState("No daily data");
    return;
  }
  const width = 920;
  const height = 280;
  const pad = 34;
  const values = daily.map((row) => row.netProfit);
  const min = Math.min(0, ...values);
  const max = Math.max(...values, 1);
  const x = (index) => pad + (index * (width - pad * 2)) / Math.max(daily.length - 1, 1);
  const y = (value) => height - pad - ((value - min) / (max - min || 1)) * (height - pad * 2);
  const points = daily.map((row, index) => `${x(index)},${y(row.netProfit)}`).join(" ");
  const bars = daily
    .map((row, index) => {
      const assetHeight = Math.max(2, ((row.assetProfit - min) / (max - min || 1)) * 80);
      const liabilityHeight = Math.max(2, ((row.liabilityProfit - min) / (max - min || 1)) * 80);
      return `
        <rect class="asset-bar" x="${x(index) - 11}" y="${height - pad - assetHeight}" width="9" height="${assetHeight}" rx="1"></rect>
        <rect class="liability-bar" x="${x(index) + 2}" y="${height - pad - liabilityHeight}" width="9" height="${liabilityHeight}" rx="1"></rect>
      `;
    })
    .join("");
  els.trendChart.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" class="line-chart" role="img" aria-label="Daily FTP trend">
      <line class="axis" x1="${pad}" x2="${width - pad}" y1="${height - pad}" y2="${height - pad}"></line>
      ${bars}
      <polyline class="trend-line" points="${points}"></polyline>
      ${daily
        .map((row, index) => `<circle class="trend-point" cx="${x(index)}" cy="${y(row.netProfit)}" r="4"><title>${row.date}: ${money(row.netProfit)}</title></circle>`)
        .join("")}
      ${daily
        .map((row, index) => `<text class="x-label" x="${x(index)}" y="${height - 8}" text-anchor="middle">${row.date.slice(5)}</text>`)
        .join("")}
    </svg>
  `;
}

function renderScatter(products) {
  const width = 500;
  const height = 320;
  const pad = 42;
  const maxBalance = Math.max(...products.map((row) => row.balance), 1);
  const maxProfit = Math.max(...products.map((row) => row.ftpProfit), 1);
  const x = (value) => pad + (value / maxBalance) * (width - pad * 2);
  const y = (value) => height - pad - (value / maxProfit) * (height - pad * 2);
  els.scatterChart.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" class="scatter" role="img" aria-label="Product balance versus FTP profit">
      <line class="axis" x1="${pad}" x2="${width - pad}" y1="${height - pad}" y2="${height - pad}"></line>
      <line class="axis" x1="${pad}" x2="${pad}" y1="${pad}" y2="${height - pad}"></line>
      ${products
        .map((row, index) => `
          <g>
            <circle class="scatter-point c${index}" cx="${x(row.balance)}" cy="${y(row.ftpProfit)}" r="${8 + Math.min(14, row.records / 12)}"></circle>
            <text class="point-label" x="${x(row.balance) + 12}" y="${y(row.ftpProfit) - 6}">${escapeHtml(row.product)}</text>
          </g>
        `)
        .join("")}
    </svg>
  `;
}

function renderHeatmap(model) {
  const max = Math.max(...model.cells.map((cell) => Math.abs(cell.value)), 1);
  els.heatmap.innerHTML = `
    <div class="heatmap-grid" style="grid-template-columns: 110px repeat(${model.products.length}, minmax(110px, 1fr));">
      <div class="heat-head"></div>
      ${model.products.map((product) => `<div class="heat-head">${escapeHtml(product)}</div>`).join("")}
      ${model.branches
        .map(
          (branch) => `
          <div class="heat-row-head">${escapeHtml(branch)}</div>
          ${model.products
            .map((product) => {
              const cell = model.cells.find((item) => item.branch === branch && item.product === product);
              const intensity = Math.min(0.85, Math.abs(cell.value) / max);
              const color = cell.value >= 0 ? `rgba(29, 128, 97, ${0.12 + intensity})` : `rgba(190, 69, 69, ${0.14 + intensity})`;
              return `<div class="heat-cell" style="background:${color}"><strong>${money(cell.value, true)}</strong><span>${cell.records} rows</span></div>`;
            })
            .join("")}
        `,
        )
        .join("")}
    </div>
  `;
}

function renderScenario() {
  const records = filterRecords(state.records, state.filters);
  const simulated = simulate(records, state.shocks);
  const current = records.reduce((sum, record) => sum + record.ftp_profit, 0);
  const simulatedTotal = simulated.reduce((sum, record) => sum + record.simulated_ftp_profit, 0);
  const delta = simulatedTotal - current;
  const products = scenarioByProduct(simulated);

  els.scenarioKpis.innerHTML = [
    kpi("Current FTP", money(current), "Filtered portfolio"),
    kpi("Simulated FTP", money(simulatedTotal), "After rate shocks"),
    kpi("Impact", money(delta), delta >= 0 ? "Positive movement" : "Negative movement"),
    kpi("Impact %", current ? ratio((delta / current) * 100) : "0.00%", "Against current FTP"),
  ].join("");

  els.scenarioTable.innerHTML = table(
    ["Product", "Current", "Simulated", "Impact"],
    products.map((row) => [row.product, money(row.current), money(row.simulated), money(row.delta)]),
  );
}

function renderGovernance() {
  els.configTable.innerHTML = table(
    ["Product", "Type", "Benchmark", "Liquidity", "Other", "Effective", "Status"],
    state.metadata.products.map((row) => [
      row.product,
      badge(row.type === "A" ? "Asset" : "Liability", row.type === "A" ? "asset" : "liability"),
      ratio(row.benchmarkRate),
      ratio(row.liquidityCost),
      ratio(row.otherCost),
      `${row.effectiveFrom} to ${row.effectiveTo}`,
      badge(row.status, "active"),
    ]),
  );

  els.controlSummary.innerHTML = `
    <div class="control-list">
      ${control("Upload Batch", state.metadata.sourceWorkbook)}
      ${control("Records Loaded", number(state.metadata.recordCount, 0))}
      ${control("Configuration Version", "Sample v1")}
      ${control("Calculation Mode", "Deterministic")}
      ${control("Exception Policy", "Negative FTP and interest mismatch")}
      ${control("Audit Trail", "Raw values, normalized values, config version")}
    </div>
  `;
}

function exportCurrentCsv() {
  const records = filterRecords(state.records, state.filters);
  const headers = ["date", "branch", "account", "type", "product", "balance", "roi", "benchmark_rate", "liquidity_cost", "other_cost", "ftp_rate", "ftp_profit", "customer_interest"];
  const csv = [
    headers.join(","),
    ...records.map((record) => headers.map((key) => csvCell(record[key])).join(",")),
  ].join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "ftp-results-export.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function kpi(label, value, meta) {
  return `
    <article class="kpi-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(meta)}</small>
    </article>
  `;
}

function table(headers, rows) {
  if (!rows.length) return emptyState("No matching data");
  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${headers.map((header) => `<th>${escapeHtml(header)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function sectionTable(title, headers, rows) {
  return `
    <div>
      <h3 class="mini-heading">${escapeHtml(title)}</h3>
      ${table(headers, rows)}
    </div>
  `;
}

function badge(text, tone) {
  return `<span class="type-badge ${tone}">${escapeHtml(text)}</span>`;
}

function control(label, value) {
  return `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`;
}

function emptyState(message) {
  return `<div class="empty-state">${escapeHtml(message)}</div>`;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function csvCell(value) {
  const text = String(value ?? "");
  if (/[",\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}
