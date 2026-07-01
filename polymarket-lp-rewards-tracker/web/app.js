"use strict";

let REFRESH = 30;
let countdown = REFRESH;
let chart = null;

const $ = (id) => document.getElementById(id);
const usd = (n) => (n == null ? "–" : "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const cents = (n) => (n == null ? "–" : Number(n).toFixed(1) + "¢");
const pct = (n) => (n == null ? "–" : (Number(n) * 100).toFixed(2) + "%");
const price = (n) => (n == null ? "–" : Number(n).toFixed(3));

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(url + " -> " + r.status);
  return r.json();
}

function pill(ok, yes = "yes", no = "no") {
  return `<span class="pill ${ok ? "yes" : "no"}">${ok ? yes : no}</span>`;
}

function renderCards(sum) {
  const t = sum.earnings_totals || {};
  const bal = (sum.balances && sum.balances[0]) || {};
  const cards = [
    { label: "Paid rewards", value: usd(t.paid), cls: "green" },
    { label: "Pending rewards", value: usd(t.pending), cls: "amber" },
    { label: "Active programs", value: sum.active_programs ?? "–" },
    { label: "Eligible orders", value: `${sum.eligible_orders ?? 0}/${sum.open_orders ?? 0}` },
    { label: "Account balance", value: usd(bal.current), sub: bal.buying_power != null ? "buying power " + usd(bal.buying_power) : "" },
  ];
  $("cards").innerHTML = cards
    .map(
      (c) => `<div class="card"><div class="label">${c.label}</div>
        <div class="value ${c.cls || ""}">${c.value}</div>
        ${c.sub ? `<div class="sub">${c.sub}</div>` : ""}</div>`
    )
    .join("");
}

function renderMeta(meta) {
  REFRESH = meta.refresh_seconds || 30;
  const mb = $("mode-badge");
  mb.textContent = meta.mode === "demo" ? "DEMO DATA" : "LIVE";
  mb.className = "badge " + meta.mode;
  const ab = $("auth-badge");
  ab.textContent = meta.authenticated ? "authenticated" : "public only";
  ab.className = "badge " + (meta.authenticated ? "auth-yes" : "auth-no");
  $("foot-note").textContent =
    meta.mode === "demo"
      ? "Showing synthetic demo data — set LPT_DEMO_MODE=false and add API keys for live data."
      : meta.authenticated
      ? ""
      : "No API credentials: earnings/orders/balances need keys; showing public program data only.";
}

function renderEarningsChart(earn) {
  const s = earn.series || [];
  const labels = s.map((p) => p.date.slice(5));
  const data = {
    labels,
    datasets: [
      { type: "bar", label: "Paid", data: s.map((p) => p.paid), backgroundColor: "#3fb950", stack: "e" },
      { type: "bar", label: "Pending", data: s.map((p) => p.pending), backgroundColor: "#d29922", stack: "e" },
      { type: "line", label: "Cumulative", data: s.map((p) => p.cumulative), borderColor: "#4f8cff", backgroundColor: "#4f8cff", yAxisID: "y1", tension: 0.25, pointRadius: 2 },
    ],
  };
  const opts = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { labels: { color: "#8b949e" } } },
    scales: {
      x: { stacked: true, ticks: { color: "#8b949e" }, grid: { color: "#222b36" } },
      y: { stacked: true, ticks: { color: "#8b949e", callback: (v) => "$" + v }, grid: { color: "#222b36" } },
      y1: { position: "right", ticks: { color: "#4f8cff", callback: (v) => "$" + v }, grid: { drawOnChartArea: false } },
    },
  };
  if (!window.Chart) return;
  if (chart) {
    chart.data = data;
    chart.update();
  } else {
    chart = new Chart($("earnings-chart"), { data, options: opts });
  }
}

function table(el, cols, rows, emptyMsg) {
  if (!rows.length) {
    el.innerHTML = `<tbody><tr><td class="empty" colspan="${cols.length}">${emptyMsg}</td></tr></tbody>`;
    return;
  }
  const head = "<thead><tr>" + cols.map((c) => `<th>${c.h}</th>`).join("") + "</tr></thead>";
  const body =
    "<tbody>" +
    rows.map((r) => "<tr>" + cols.map((c) => `<td>${c.f(r)}</td>`).join("") + "</tr>").join("") +
    "</tbody>";
  el.innerHTML = head + body;
}

function renderMarkets(earn) {
  table(
    $("markets-table"),
    [
      { h: "Market", f: (r) => `<span class="slug">${r.slug || "—"}</span>` },
      { h: "Paid", f: (r) => usd(r.paid) },
      { h: "Pending", f: (r) => usd(r.pending) },
      { h: "Total", f: (r) => `<b>${usd(r.total)}</b>` },
    ],
    earn.markets || [],
    earn.authenticated ? "No earnings in range." : "Add API keys to see your earnings."
  );
}

function renderBalances(b) {
  table(
    $("balances-table"),
    [
      { h: "Currency", f: (r) => r.currency },
      { h: "Balance", f: (r) => usd(r.current) },
      { h: "Buying power", f: (r) => usd(r.buying_power) },
      { h: "In open orders", f: (r) => usd(r.open_orders) },
    ],
    b.balances || [],
    "No balances (needs API keys)."
  );
}

function renderPrograms(p) {
  table(
    $("programs-table"),
    [
      { h: "Market", f: (r) => `<span class="slug">${r.slug}</span>` },
      { h: "Type", f: (r) => `<span class="muted">${(r.program_type || "").replace("Program", "")}</span>` },
      { h: "Period", f: (r) => r.period || "–" },
      { h: "Pool", f: (r) => usd(r.reward_pool) },
      { h: "Target size", f: (r) => (r.target_size != null ? Number(r.target_size).toLocaleString() : "–") },
      { h: "Mid", f: (r) => price(r.midpoint) },
      { h: "Reward zone", f: (r) => (r.reward_zone ? `${price(r.reward_zone.lower)}–${price(r.reward_zone.upper)}` : "–") },
      { h: "My orders", f: (r) => r.my_orders || 0 },
      { h: "2-sided", f: (r) => pill(r.my_two_sided) },
      { h: "My share", f: (r) => pct(r.my_share) },
      { h: "Est. (period)", f: (r) => `<b>${usd(r.my_estimated_period_usd)}</b>` },
    ],
    p.programs || [],
    "No active incentive programs found."
  );
}

function renderOrders(o) {
  table(
    $("orders-table"),
    [
      { h: "Market", f: (r) => `<span class="slug">${r.slug}</span>` },
      { h: "Side", f: (r) => `<span class="side-${r.side}">${r.side}</span>` },
      { h: "Price", f: (r) => price(r.price) },
      { h: "Size", f: (r) => Number(r.size).toLocaleString() },
      { h: "State", f: (r) => `<span class="muted">${r.state || ""}</span>` },
      { h: "Mid", f: (r) => price(r.midpoint) },
      { h: "Spread", f: (r) => cents(r.spread_cents) },
      { h: "Min size", f: (r) => Number(r.min_size).toLocaleString() },
      { h: "Program", f: (r) => pill(r.has_program) },
      { h: "Eligible", f: (r) => pill(r.qualifies) },
      { h: "Note", f: (r) => `<span class="muted">${r.reason}</span>` },
    ],
    o.orders || [],
    o.orders ? "No open orders." : "Add API keys to see your orders."
  );
}

async function refresh() {
  try {
    const [sum, earn, programs, orders, balances] = await Promise.all([
      getJSON("/api/summary"),
      getJSON("/api/earnings"),
      getJSON("/api/programs"),
      getJSON("/api/orders"),
      getJSON("/api/balances"),
    ]);
    renderMeta(sum.meta);
    renderCards(sum);
    renderEarningsChart(earn);
    renderMarkets(earn);
    renderPrograms(programs);
    renderOrders(orders);
    renderBalances(balances);
  } catch (e) {
    console.error(e);
    $("foot-note").textContent = "Error loading data: " + e.message;
  }
  countdown = REFRESH;
}

function tick() {
  countdown -= 1;
  if (countdown <= 0) refresh();
  $("countdown").textContent = Math.max(0, countdown);
}

$("refresh-btn").addEventListener("click", refresh);
refresh();
setInterval(tick, 1000);
