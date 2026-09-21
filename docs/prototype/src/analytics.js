const DAY_FACTOR = 36500;

export function money(value, compact = false) {
  const amount = Number(value || 0);
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    notation: compact ? "compact" : "standard",
    maximumFractionDigits: compact ? 2 : 2,
  }).format(amount);
}

export function number(value, digits = 2) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(Number(value || 0));
}

export function ratio(value, digits = 2) {
  return `${number(value, digits)}%`;
}

export function unique(records, key) {
  return [...new Set(records.map((record) => record[key]))].sort((a, b) =>
    String(a).localeCompare(String(b), undefined, { numeric: true }),
  );
}

export function filterRecords(records, filters) {
  const accountTerm = filters.account.trim();
  return records.filter((record) => {
    if (filters.from && record.date < filters.from) return false;
    if (filters.to && record.date > filters.to) return false;
    if (filters.branch !== "ALL" && record.branch !== filters.branch) return false;
    if (filters.product !== "ALL" && record.product !== filters.product) return false;
    if (filters.type !== "ALL" && record.type !== filters.type) return false;
    if (accountTerm && !record.account.includes(accountTerm)) return false;
    return true;
  });
}

export function summarize(records) {
  const assetRows = records.filter((record) => record.type === "A");
  const liabilityRows = records.filter((record) => record.type === "L");
  const assetBalance = sum(assetRows, "balance");
  const liabilityBalance = sum(liabilityRows, "balance");
  const totalBalance = assetBalance + liabilityBalance;
  const assetFtpProfit = sum(records, "asset_ftp_profit");
  const liabilityFtpProfit = sum(records, "liability_ftp_profit");
  const netFtpProfit = assetFtpProfit + liabilityFtpProfit;
  const customerInterest = sum(records, "customer_interest");
  const interestReceivable = sum(assetRows, "customer_interest");
  const interestPayable = sum(liabilityRows, "customer_interest");
  const negativeFtpCount = records.filter((record) => record.ftp_profit < 0 || record.ftp_rate < 0).length;
  const avgFtpRate = weightedAverage(records, "ftp_rate", "balance");
  const avgRoi = weightedAverage(records, "roi", "balance");
  const branchGroups = groupBy(records, "branch").map((branch) => ({
    key: branch.key,
    net: sum(branch.records, "ftp_profit"),
  }));
  const sortedBranches = [...branchGroups].sort((a, b) => b.net - a.net);

  return {
    records: records.length,
    accounts: unique(records, "account").length,
    branches: unique(records, "branch").length,
    products: unique(records, "product").length,
    days: unique(records, "date").length,
    assetBalance,
    liabilityBalance,
    totalBalance,
    assetFtpProfit,
    liabilityFtpProfit,
    netFtpProfit,
    customerInterest,
    interestReceivable,
    interestPayable,
    ftpOnBalance: totalBalance ? (netFtpProfit * 365 / totalBalance) * 100 : 0,
    negativeFtpCount,
    avgFtpRate,
    avgRoi,
    topBranch: sortedBranches[0]?.key || "-",
    lowBranch: sortedBranches.at(-1)?.key || "-",
  };
}

export function groupBy(records, key) {
  const groups = new Map();
  for (const record of records) {
    const value = record[key];
    if (!groups.has(value)) groups.set(value, []);
    groups.get(value).push(record);
  }
  return [...groups.entries()].map(([groupKey, groupRecords]) => ({
    key: groupKey,
    records: groupRecords,
  }));
}

export function branchAnalysis(records) {
  return groupBy(records, "branch")
    .map(({ key, records: groupRecords }) => {
      const assetBalance = sum(groupRecords.filter((record) => record.type === "A"), "balance");
      const liabilityBalance = sum(groupRecords.filter((record) => record.type === "L"), "balance");
      const assetFtpProfit = sum(groupRecords, "asset_ftp_profit");
      const liabilityFtpProfit = sum(groupRecords, "liability_ftp_profit");
      const netFtpProfit = assetFtpProfit + liabilityFtpProfit;
      return {
        branch: key,
        records: groupRecords.length,
        accounts: unique(groupRecords, "account").length,
        assetBalance,
        liabilityBalance,
        assetFtpProfit,
        liabilityFtpProfit,
        netFtpProfit,
        ftpOnBalance: assetBalance + liabilityBalance ? (netFtpProfit * 365 / (assetBalance + liabilityBalance)) * 100 : 0,
        negativeCount: groupRecords.filter((record) => record.ftp_profit < 0 || record.ftp_rate < 0).length,
      };
    })
    .sort((a, b) => b.netFtpProfit - a.netFtpProfit);
}

export function productAnalysis(records) {
  return groupBy(records, "product")
    .map(({ key, records: groupRecords }) => {
      const balance = sum(groupRecords, "balance");
      const ftpProfit = sum(groupRecords, "ftp_profit");
      return {
        product: key,
        type: groupRecords[0]?.type || "-",
        records: groupRecords.length,
        balance,
        ftpProfit,
        avgRoi: weightedAverage(groupRecords, "roi", "balance"),
        avgBenchmark: weightedAverage(groupRecords, "benchmark_rate", "balance"),
        avgFtpRate: weightedAverage(groupRecords, "ftp_rate", "balance"),
        profitPerBalance: balance ? (ftpProfit * 365 / balance) * 100 : 0,
        negativeCount: groupRecords.filter((record) => record.ftp_profit < 0 || record.ftp_rate < 0).length,
      };
    })
    .sort((a, b) => b.ftpProfit - a.ftpProfit);
}

export function dailyAnalysis(records) {
  return groupBy(records, "date")
    .map(({ key, records: groupRecords }) => ({
      date: key,
      assetProfit: sum(groupRecords, "asset_ftp_profit"),
      liabilityProfit: sum(groupRecords, "liability_ftp_profit"),
      netProfit: sum(groupRecords, "ftp_profit"),
      balance: sum(groupRecords, "balance"),
      accounts: unique(groupRecords, "account").length,
    }))
    .sort((a, b) => a.date.localeCompare(b.date));
}

export function heatmap(records) {
  const branches = unique(records, "branch");
  const products = unique(records, "product");
  const cells = [];
  for (const branch of branches) {
    for (const product of products) {
      const groupRecords = records.filter((record) => record.branch === branch && record.product === product);
      cells.push({
        branch,
        product,
        value: sum(groupRecords, "ftp_profit"),
        records: groupRecords.length,
      });
    }
  }
  return { branches, products, cells };
}

export function exceptionAnalysis(records) {
  return records
    .map((record) => {
      const expectedInterest = record.balance * record.roi / DAY_FACTOR;
      const variance = record.customer_interest - expectedInterest;
      const variancePct = expectedInterest ? Math.abs(variance / expectedInterest) * 100 : 0;
      return {
        ...record,
        expectedInterest,
        interestVariance: variance,
        interestVariancePct: variancePct,
        negativeFtp: record.ftp_rate < 0 || record.ftp_profit < 0,
        interestMismatch: variancePct > 0.5 && Math.abs(variance) > 1,
      };
    })
    .filter((record) => record.negativeFtp || record.interestMismatch)
    .sort((a, b) => a.ftp_profit - b.ftp_profit);
}

export function accountRankings(records) {
  const byAccount = groupBy(records, "account").map(({ key, records: groupRecords }) => {
    const first = groupRecords[0];
    return {
      account: key,
      branch: first.branch,
      product: first.product,
      type: first.type,
      records: groupRecords.length,
      balance: sum(groupRecords, "balance"),
      ftpProfit: sum(groupRecords, "ftp_profit"),
      avgFtpRate: weightedAverage(groupRecords, "ftp_rate", "balance"),
      avgRoi: weightedAverage(groupRecords, "roi", "balance"),
    };
  });
  const sorted = [...byAccount].sort((a, b) => b.ftpProfit - a.ftpProfit);
  return {
    top: sorted.slice(0, 10),
    bottom: sorted.slice(-10).reverse(),
    all: sorted,
  };
}

export function simulate(records, shocks) {
  const benchmarkDelta = shocks.benchmarkBps / 100;
  const liquidityDelta = shocks.liquidityBps / 100;
  const otherDelta = shocks.otherBps / 100;
  return records.map((record) => {
    const benchmark = record.benchmark_rate + benchmarkDelta;
    const liquidity = record.liquidity_cost + liquidityDelta;
    const other = record.other_cost + otherDelta;
    const ftpRate =
      record.type === "L"
        ? benchmark - record.roi - liquidity - other
        : record.roi - benchmark - liquidity - other;
    const ftpProfit = record.balance * ftpRate / DAY_FACTOR;
    return {
      ...record,
      simulated_ftp_rate: ftpRate,
      simulated_ftp_profit: ftpProfit,
      simulated_asset_ftp_profit: record.type === "A" ? ftpProfit : 0,
      simulated_liability_ftp_profit: record.type === "L" ? ftpProfit : 0,
      simulated_delta: ftpProfit - record.ftp_profit,
    };
  });
}

export function scenarioByProduct(simulatedRecords) {
  return groupBy(simulatedRecords, "product")
    .map(({ key, records }) => {
      const current = sum(records, "ftp_profit");
      const simulated = sum(records, "simulated_ftp_profit");
      return {
        product: key,
        current,
        simulated,
        delta: simulated - current,
      };
    })
    .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
}

export function sum(records, key) {
  return records.reduce((total, record) => total + Number(record[key] || 0), 0);
}

function weightedAverage(records, valueKey, weightKey) {
  const denominator = sum(records, weightKey);
  if (!denominator) return 0;
  const numerator = records.reduce(
    (total, record) => total + Number(record[valueKey] || 0) * Number(record[weightKey] || 0),
    0,
  );
  return numerator / denominator;
}
