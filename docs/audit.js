'use strict';

const DATA = 'https://data-api.polymarket.com';
const REQ_GAP_MS = 350;
const REQ_TIMEOUT_MS = 30000;
const REQ_TRIES = 4;
const BATCH = 500;

let _lastReq = 0;

function isAbort(err) {
  return err && (err.name === 'AbortError' || err.code === 20);
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal && signal.aborted) {
      reject(new DOMException('cancelled', 'AbortError'));
      return;
    }
    const t = setTimeout(() => {
      if (signal) signal.removeEventListener('abort', onAbort);
      resolve();
    }, Math.max(0, ms));
    function onAbort() {
      clearTimeout(t);
      reject(new DOMException('cancelled', 'AbortError'));
    }
    if (signal) signal.addEventListener('abort', onAbort, { once: true });
  });
}

function num(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

// Python's `a or b or 0` picks the first TRUTHY raw value BEFORE float():
// None/""/0/0.0 fall through, but the string "0" does not. This matters for
// zero-valued redeems, so replicate it exactly instead of || on numbers.
function pyOr(...vals) {
  for (const v of vals) {
    if (v === null || v === undefined || v === '' || v === 0) continue;
    return v;
  }
  return 0;
}
function moneyOf(a) { return num(pyOr(a.usdcSize, a.size, 0)); }

function tsOf(a) { return Math.floor(num(a.timestamp)); }

function dayOf(ts) { return new Date(ts * 1000).toISOString().slice(0, 10); }

function round2(x) { return Math.round(x * 100) / 100; }
function round1(x) { return Math.round(x * 10) / 10; }
function round3(x) { return Math.round(x * 1000) / 1000; }

/* "A transient failure must never be mistaken for the end of a history".
   4 tries, growing backoff, 350ms gap between requests, 30s per request. */

async function getJSON(url, outerSignal, tries = REQ_TRIES) {
  let lastErr = null;
  for (let attempt = 0; attempt < tries; attempt++) {
    if (outerSignal && outerSignal.aborted) {
      throw new DOMException('cancelled', 'AbortError');
    }
    const wait = REQ_GAP_MS - (Date.now() - _lastReq);
    if (wait > 0) await sleep(wait, outerSignal);
    _lastReq = Date.now();

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), REQ_TIMEOUT_MS);
    const onOuterAbort = () => ctrl.abort();
    if (outerSignal) outerSignal.addEventListener('abort', onOuterAbort, { once: true });
    try {
      const res = await fetch(url, { signal: ctrl.signal });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return await res.json();
    } catch (ex) {
      if (outerSignal && outerSignal.aborted) {
        throw new DOMException('cancelled', 'AbortError');
      }
      lastErr = ex;
      await sleep(1500 * (attempt + 1), outerSignal);
    } finally {
      clearTimeout(timer);
      if (outerSignal) outerSignal.removeEventListener('abort', onOuterAbort);
    }
  }
  throw new Error(`request failed after ${tries} attempts: ${String(lastErr).slice(0, 120)}`);
}

/* Dedupe key: (transactionHash, asset, type, size, timestamp, side, usdcSize) */

function eventKey(a) {
  return [a.transactionHash, a.asset, a.type, String(a.size),
          String(a.timestamp), a.side, String(a.usdcSize)].join('|');
}

/* Walks backwards with an `end` cursor. Two hazards handled, same as the
   Python: a batch entirely at one timestamp stalls a naive cursor (step end
   back 1s, give up only after 2 consecutive stalls), and a failed request
   retries rather than ending the walk. `out` is caller-owned so a cancelled
   walk still leaves its partial events in the caller's hands. */
async function fetchHistory(addr, maxEvents, signal, out, stats, onProgress) {
  const seen = new Set();
  let end = null;
  let stalls = 0;
  while (out.length < maxEvents) {
    let url = `${DATA}/activity?user=${addr}&limit=${BATCH}`;
    if (end !== null) url += `&end=${end}`;
    const batch = await getJSON(url, signal);
    stats.requests += 1;
    if (!Array.isArray(batch) || batch.length === 0) return true; // complete
    let fresh = 0;
    for (const a of batch) {
      const k = eventKey(a);
      if (seen.has(k)) continue;
      seen.add(k);
      out.push(a);
      fresh += 1;
    }
    let oldest = Infinity;
    for (const a of batch) oldest = Math.min(oldest, tsOf(a));
    stats.oldest = oldest;
    onProgress(out.length, oldest, stats.requests);
    if (fresh === 0 || (end !== null && oldest >= end)) {
      stalls += 1;
      if (stalls >= 2) return true;
      end = (end === null ? oldest : Math.min(end, oldest)) - 1;
      continue;
    }
    stalls = 0;
    end = oldest;
  }
  return false; // ceiling hit — caller must say the period is partial
}


function computeCore(acts) {
  const trades = acts.filter((a) => a.type === 'TRADE');
  const redeems = acts.filter((a) => a.type === 'REDEEM' || a.type === 'CLAIM');
  const rebates = acts.filter((a) => {
    const ty = String(a.type || '').toUpperCase();
    return ty.includes('REBATE') || ty === 'REWARD';
  });

  let fees = 0, buys = 0, sells = 0;
  let makerFills = 0, takerFills = 0;
  const perMarket = new Map();
  const byDay = new Map();
  const prices = [];
  const bump = (map, key, v) => map.set(key, (map.get(key) || 0) + v);

  for (const t of trades) {
    const px = num(t.price);
    const sz = num(t.size);
    const usdc = num(t.usdcSize);
    const notional = px * sz;
    // Cash flow is what actually moved in USDC; the fee is the gap between
    // that and the notional, which is where Polymarket hides it.
    let fee, flow;
    if (t.side === 'BUY') {
      fee = Math.max(0, usdc - notional);
      flow = -usdc;
      prices.push(px);
    } else {
      fee = Math.max(0, notional - usdc);
      flow = usdc;
    }
    fees += fee;
    if (fee < 0.0001 * Math.max(notional, 1.0)) makerFills += 1;
    else takerFills += 1;
    const day = dayOf(tsOf(t));
    if (t.side === 'BUY') buys += usdc;
    else sells += usdc;
    bump(perMarket, t.conditionId, flow);
    bump(byDay, day, flow);
  }

  let redeemed = 0, zeroRedeems = 0;
  for (const r of redeems) {
    const v = moneyOf(r);
    if (v === 0) zeroRedeems += 1;
    redeemed += v;
    bump(perMarket, r.conditionId, v);
    bump(byDay, dayOf(tsOf(r)), v);
  }

  // A merge turns a paired YES+NO back into a dollar and a split does the
  // reverse. Wallets that recycle capital this way move six figures through
  // these events; ignoring them reads as a catastrophic loss that never
  // happened.
  let merged = 0, splitOut = 0;
  for (const a of acts) {
    const ty = String(a.type || '').toUpperCase();
    if (ty !== 'MERGE' && ty !== 'SPLIT' && ty !== 'CONVERSION') continue;
    const v = moneyOf(a);
    const day = dayOf(tsOf(a));
    if (ty === 'MERGE') {
      merged += v;
      bump(perMarket, a.conditionId, v);
      bump(byDay, day, v);
    } else if (ty === 'SPLIT') {
      splitOut += v;
      bump(perMarket, a.conditionId, -v);
      bump(byDay, day, -v);
    }
  }

  let rebateTotal = 0;
  for (const r of rebates) rebateTotal += moneyOf(r);

  return { trades, fees, buys, sells, makerFills, takerFills, perMarket,
           byDay, prices, redeemed, zeroRedeems, merged, splitOut, rebateTotal };
}

async function runAudit(addr, maxEvents, signal, onProgress) {
  const acts = [];
  const stats = { requests: 0, oldest: null };
  let complete;
  let partial = false;
  try {
    complete = await fetchHistory(addr, maxEvents, signal, acts, stats, onProgress);
  } catch (ex) {
    if (!isAbort(ex)) throw ex;
    complete = false;     // cancelled mid-walk: report the slice, flagged
    partial = true;
  }
  if (acts.length === 0) {
    if (partial) throw new DOMException('cancelled', 'AbortError');
    return { error: 'No activity found, or the address is invalid.' };
  }

  const c = computeCore(acts);

  const auxSignal = partial ? null : signal;

  let portfolio = 0;
  try {
    const v = await getJSON(`${DATA}/value?user=${addr}`, auxSignal, 2);
    portfolio = num(Array.isArray(v) && v.length ? v[0].value : 0);
  } catch (ex) {
    if (isAbort(ex)) throw ex;
    portfolio = 0;
  }

  const cash = c.sells + c.redeemed + c.merged - c.buys - c.splitOut;
  const realPnl = cash + c.rebateTotal + portfolio;

  let official = null;
  try {
    const lb = await getJSON(
      `${DATA}/v1/leaderboard?timePeriod=all&orderBy=PNL&limit=1&offset=0` +
      `&category=overall&user=${addr}`, auxSignal, 2);
    if (Array.isArray(lb) && lb.length) official = num(lb[0].pnl);
  } catch (ex) {
    if (isAbort(ex)) throw ex;
    official = null;
  }

  const vals = [...c.perMarket.values()].sort((a, b) => b - a);
  const gains = vals.filter((v) => v > 0);
  const gainsSum = gains.reduce((s, v) => s + v, 0);
  const top5 = vals.slice(0, 5).reduce((s, v) => s + v, 0);
  const days = [...c.byDay.keys()].sort();
  const half = Math.floor(days.length / 2);
  const h1 = days.slice(0, half).reduce((s, d) => s + c.byDay.get(d), 0);
  const h2 = days.slice(half).reduce((s, d) => s + c.byDay.get(d), 0);
  const posDays = days.filter((d) => c.byDay.get(d) > 0).length;

  // Reconciliation against an INDEPENDENT number. Comparing our ledger to our
  // own cash flow proves nothing: both come from the same rows, so the check
  // could never fail. The venue's public figure is fee-blind and rebate-blind,
  // which gives a real identity to test:  official ≈ real + fees − rebates.
  // A wide gap means events are missing (zero-valued redeems, unhandled
  // transfer types) and the numbers must not be published as fact.
  // What it cannot test, by construction, is the rebate line: real_pnl already
  // contains rebates, so they cancel out of real + fees - rebates. An outside
  // reviewer had to point that out. The identity checks cash flow, open value
  // and fees against the venue. It never checks the subsidy.
  const expectedOfficial = realPnl + c.fees - c.rebateTotal;
  let reconciled = null;
  let gapPct = null;
  if (official !== null && Math.abs(official) > 1) {
    gapPct = Math.abs(expectedOfficial - official) / Math.max(Math.abs(official), 1.0);
    reconciled = gapPct <= 0.05;
  }

  // A derived number the same size as the books' own error bar has no sign,
  // so the effect is compared against the run's reconciliation residual before
  // anything is claimed about it. This lives in code because prose was not
  // enough: the same rule was published as prose on 2026-08-09 and broken that
  // same day by the person who wrote it, who called $4,218 of effect "inside"
  // a $2,567 residual. It is not inside. It is resolved, and positive, and the
  // identity's other estimator agrees by construction: official - fees comes
  // to $1,651, which is 4,218 - 2,567 exactly. The first run of this coded
  // version contradicted the site copy shipped that morning.
  const withoutRebate = realPnl - c.rebateTotal;
  const residUsd = (official !== null && Math.abs(official) > 1)
    ? Math.abs(expectedOfficial - official) : null;
  let withoutRebateSign = null;
  if (c.rebateTotal > 0) {
    if (residUsd === null) withoutRebateSign = 'UNCHECKED';
    else if (Math.abs(withoutRebate) <= residUsd) withoutRebateSign = 'UNRESOLVED';
    else withoutRebateSign = withoutRebate > 0 ? 'POSITIVE' : 'NEGATIVE';
  }

  const ts = acts.map(tsOf).filter((t) => t > 0);

  return {
    address: addr,
    run_at: new Date().toISOString().slice(0, 10),
    complete_history: complete,
    partial_run: partial,
    reconciled: reconciled,
    gap_vs_identity_pct: gapPct !== null ? round1(100 * gapPct) : null,
    zero_value_redeems: c.zeroRedeems,
    merges_usd: round2(c.merged),
    first_activity: ts.length ? dayOf(Math.min(...ts)) : null,
    last_activity: ts.length ? dayOf(Math.max(...ts)) : null,
    events: acts.length,
    trades: c.trades.length,
    markets: c.perMarket.size,
    bought_usd: round2(c.buys),
    sold_usd: round2(c.sells),
    redeemed_usd: round2(c.redeemed),
    fees_paid: round2(c.fees),
    rebates: round2(c.rebateTotal),
    open_portfolio: round2(portfolio),
    REAL_PNL: round2(realPnl),
    official_pnl_prefee: official !== null ? round2(official) : null,
    gap_vs_official: official !== null ? round2(official - realPnl) : null,
    maker_fills: c.makerFills,
    taker_fills: c.takerFills,
    pct_maker: round1(100 * c.makerFills / Math.max(1, c.trades.length)),
    avg_buy_price: c.prices.length
      ? round3(c.prices.reduce((s, v) => s + v, 0) / c.prices.length) : null,
    top5_pct_of_gains: gainsSum > 0 ? round1(100 * top5 / gainsSum) : null,
    half_1: round2(h1),
    half_2: round2(h2),
    days_traded: days.length,
    positive_days: posDays,
    trading_without_rebate: round2(withoutRebate),
    without_rebate_sign: withoutRebateSign,
    lives_on_rebate: c.rebateTotal > 0 && (realPnl - c.rebateTotal) <= 0,
    requests_made: stats.requests,
  };
}

function verdict(a) {
  const out = [];
  if (a.partial_run) {
    out.push({ cls: 'warn', text:
      `PARTIAL RUN — cancelled at ${a.events.toLocaleString('en-US')} events. ` +
      'Every figure covers only the most recent slice of the history.' });
  }
  if (a.reconciled === false) {
    out.push({ cls: 'flag', text:
      `NOT RELIABLE: the books do not tie out against the public figure ` +
      `(gap ${a.gap_vs_identity_pct}%). Missing events: ${a.zero_value_redeems} ` +
      'redemptions come back zero-valued from the API. Do not publish these numbers.' });
  } else if (a.reconciled === null) {
    out.push({ cls: 'warn', text:
      'No public figure to check against: these numbers lack cross-verification.' });
  }
  if (!a.complete_history && !a.partial_run) {
    out.push({ cls: 'warn', text:
      'History truncated by the event cap: the result covers only the most ' +
      'recent period, not the whole life of the wallet.' });
  }
  if (a.without_rebate_sign === 'NEGATIVE') {
    out.push({ cls: 'flag', text:
      'TRADING LOSES — the profit comes from the volume rebate. ' +
      'Copying these trades without that tier is losing.' });
  } else if (a.without_rebate_sign === 'UNRESOLVED') {
    out.push({ cls: 'warn', text:
      'Without the rebate the result is smaller than this run’s ' +
      'reconciliation residual: sign UNRESOLVED. The rebate dominates the ' +
      'income; the trading shows no demonstrated edge.' });
  } else if (a.without_rebate_sign === 'POSITIVE' && a.rebates > 0 &&
             a.REAL_PNL > 0 && a.rebates > 0.5 * a.REAL_PNL) {
    out.push({ cls: 'warn', text:
      `The rebate is the dominant income source (${Math.round(100 * a.rebates / a.REAL_PNL)}% ` +
      'of net): the trading adds little, and these economics do not replicate ' +
      'without that tier.' });
  }
  if (a.gap_vs_official && a.gap_vs_official > 0) {
    out.push({ cls: 'norm', text:
      `The public profile overstates by $${Math.round(a.gap_vs_official).toLocaleString('en-US')} ` +
      '(it does not subtract the fee).' });
  }
  const t5 = a.top5_pct_of_gains;
  if (t5 && t5 > 60) {
    out.push({ cls: 'norm', text:
      `Concentrated: ${Math.round(t5)}% of the gains sit in 5 markets — ` +
      'a streak, not a method.' });
  }
  if (a.half_1 !== null && a.half_1 < 0 && a.half_2 > 0) {
    out.push({ cls: 'norm', text:
      'The first half of its history was negative: the result depends on ' +
      'one period, not a stable edge.' });
  }
  if ((a.pct_maker || 0) > 90) {
    out.push({ cls: 'norm', text:
      'Near-pure maker (zero fee): the business is quoting, not picking ' +
      'winners. Its trades are not copyable as picks.' });
  }
  if (out.length === 0) {
    out.push({ cls: 'ok', text: 'No obvious flags: gains spread out and consistent.' });
  }
  return out;
}

const $ = (id) => document.getElementById(id);

const form = $('audForm');
if (form) {
  const addrInput = $('addr');
  const capSelect = $('cap');
  const runBtn = $('runBtn');
  const cancelBtn = $('cancelBtn');
  const errorEl = $('audError');
  const progressEl = $('audProgress');
  const progressText = $('progressText');
  const reportEl = $('report');
  const reportTitle = $('reportTitle');
  const reportMeta = $('reportMeta');
  const reportBody = $('reportBody');
  const downloadBtn = $('downloadBtn');
  const exampleLink = $('exampleLink');
  const copyLinkBtn = $('copyLinkBtn');
  const linkFallback = $('linkFallback');

  let controller = null;
  let lastResult = null;

  const ADDR_RE = /^0x[0-9a-fA-F]{40}$/;
  const ADDR_ERR =
    'That is not a wallet address. Expected 0x followed by 40 hex characters.';
  const CAPS = new Set([...capSelect.options].map((o) => o.value));

  const fmtInt = (n) => Number(n).toLocaleString('en-US');
  function fmtUSD(n) {
    const v = Number(n) || 0;
    const abs = Math.abs(v).toLocaleString('en-US',
      { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    return (v < 0 ? '−$' : '$') + abs;
  }
  function fmtSigned(n) {
    const v = Number(n) || 0;
    const abs = Math.round(Math.abs(v)).toLocaleString('en-US');
    return (v < 0 ? '−' : '+') + abs;
  }

  function showError(msg) {
    errorEl.textContent = msg;
    errorEl.hidden = false;
  }
  function clearError() {
    errorEl.hidden = true;
    errorEl.textContent = '';
  }

  function setRunning(on) {
    runBtn.disabled = on;
    cancelBtn.disabled = !on;
    addrInput.disabled = on;
    capSelect.disabled = on;
    progressEl.classList.toggle('on', on);
  }

  function line(text, cls) {
    const div = document.createElement('div');
    div.className = 'rline' + (cls ? ' ' + cls : '');
    if (text === '') div.classList.add('gap');
    div.textContent = text;
    return div;
  }

  function renderReport(a) {
    reportBody.replaceChildren();
    reportTitle.textContent = `audit ${a.address.slice(0, 10)}…${a.address.slice(-4)}`;
    const shape = a.partial_run
      ? 'PARTIAL — cancelled mid-walk'
      : (a.complete_history ? 'full history' : 'capped history');
    reportMeta.textContent = a.run_at ? `${shape} · run ${a.run_at}` : shape;

    const add = (t, c) => reportBody.appendChild(line(t, c));

    add(`=== ${a.address} ===`, 'head');
    add(`  active ${a.first_activity} → ${a.last_activity} | ` +
        `${fmtInt(a.trades)} trades in ${fmtInt(a.markets)} markets | ` +
        `${fmtInt(a.events)} events`, 'dim');
    add('');
    add(`  REAL PNL (fees and rebates included): ${fmtUSD(a.REAL_PNL)}`, 'big');
    if (a.official_pnl_prefee !== null) {
      add(`  the public profile says:              ${fmtUSD(a.official_pnl_prefee)}   ← pre-fee`, 'warn');
    } else {
      add('  the public profile says:              (no figure available)', 'dim');
    }
    add('');
    add(`  fees paid ${fmtUSD(a.fees_paid)} | rebates ${fmtUSD(a.rebates)} | ` +
        `maker ${a.pct_maker}% of fills`);
    add(`  open portfolio ${fmtUSD(a.open_portfolio)} | bought ${fmtUSD(a.bought_usd)} | ` +
        `sold ${fmtUSD(a.sold_usd)} | redeemed ${fmtUSD(a.redeemed_usd)}`, 'dim');
    add(`  top-5 markets = ${a.top5_pct_of_gains !== null ? a.top5_pct_of_gains + '%' : 'n/a'} of gains | ` +
        `cash halves ${fmtSigned(a.half_1)} / ${fmtSigned(a.half_2)} | ` +
        `days ${a.positive_days}/${a.days_traded} positive`, 'dim');
    add('  (shape lines are cash flow: no rebates, no open book)', 'dim');
    if (a.gap_vs_identity_pct !== null) {
      add(`  reconciliation: gap ${a.gap_vs_identity_pct}% vs identity ` +
          `official ≈ real + fees − rebates`,
          a.reconciled ? 'ok' : 'flag');
    }
    add('');
    add('  READING:', 'head');
    for (const v of verdict(a)) {
      add(`   - ${v.text}`, v.cls === 'norm' ? '' : v.cls);
    }

    reportEl.classList.add('on');
    reportEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  function syncUrl(addr, cap) {
    const url = new URL(window.location.href);
    url.searchParams.set('w', addr);
    url.searchParams.set('cap', String(cap));
    history.replaceState(null, '', url);
  }

  async function run() {
    clearError();
    const addr = addrInput.value.trim();
    if (!ADDR_RE.test(addr)) {
      showError(ADDR_ERR);
      addrInput.focus();
      return;
    }
    const cap = parseInt(capSelect.value, 10) || 200000;

    controller = new AbortController();
    lastResult = null;
    reportEl.classList.remove('on');
    setRunning(true);
    progressText.textContent = 'starting the walk…';

    try {
      const result = await runAudit(addr.toLowerCase(), cap, controller.signal,
        (events, oldestTs, requests) => {
          progressText.textContent =
            `walking history… ${fmtInt(events)} events | ` +
            `back to ${dayOf(oldestTs)} | ${fmtInt(requests)} requests`;
        });
      if (result.error) {
        showError(result.error);
      } else {
        lastResult = result;
        renderReport(result);
        syncUrl(result.address, cap);
      }
    } catch (ex) {
      if (isAbort(ex)) {
        showError('Cancelled before any events arrived — nothing to report.');
      } else {
        showError('The audit could not finish: ' + String(ex && ex.message || ex) +
          '. The API may be rate-limiting or unreachable; wait a moment and run it again.');
      }
    } finally {
      setRunning(false);
      controller = null;
    }
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (!runBtn.disabled) run();
  });

  cancelBtn.addEventListener('click', () => {
    if (controller) {
      progressText.textContent = 'cancelling — finishing the partial report…';
      controller.abort();
    }
  });

  exampleLink.addEventListener('click', (e) => {
    e.preventDefault();
    addrInput.value = exampleLink.textContent.trim();
    addrInput.focus();
  });

  downloadBtn.addEventListener('click', () => {
    if (!lastResult) return;
    const blob = new Blob([JSON.stringify(lastResult, null, 1)],
      { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `polyaudit-${lastResult.address.slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  });

  copyLinkBtn.addEventListener('click', async () => {
    if (!lastResult) return;
    const href = window.location.href;
    try {
      if (!navigator.clipboard) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(href);
      linkFallback.hidden = true;
      const prev = copyLinkBtn.textContent;
      copyLinkBtn.textContent = 'Copied';
      setTimeout(() => { copyLinkBtn.textContent = prev; }, 1600);
    } catch {
      linkFallback.value = href;
      linkFallback.hidden = false;
      linkFallback.focus();
      linkFallback.select();
    }
  });

  // Address and cap only. Recomputing here is what stops a forged link.
  (function bootFromUrl() {
    const params = new URLSearchParams(location.search);
    const w = (params.get('w') || '').trim();
    if (!w) return;
    addrInput.value = w;
    const cap = params.get('cap');
    if (cap && CAPS.has(cap)) capSelect.value = cap;
    if (!ADDR_RE.test(w)) { showError(ADDR_ERR); return; }
    run();
  })();
}
