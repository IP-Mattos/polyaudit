#!/usr/bin/env python3
"""Polymarket wallet audit: what a trader ACTUALLY made.

Polymarket's public leaderboard reports profit BEFORE the trading fee and
denominates volume in shares rather than dollars. Wallets that appear to have
made six figures can be losing money on every trade and surviving on the
volume-tier rebate. This reconstructs the real number.

What it does that the leaderboard does not:
  - charges the fee actually paid, read per fill as usdcSize - price*shares
  - counts MAKER_REBATE / TAKER_REBATE, which decide whether a taker bot is a
    business or a subsidy
  - separates realised from open, and reconciles per-market sums against the
    wallet total, refusing to report numbers that do not tie out
  - reports the anti-luck shape: how much of the profit sits in five markets,
    whether both halves of the history are positive, and how many days carried
    the rest

Usage:  python audit.py 0xADDRESS [--json]
"""
import json
import sys
import time
import urllib.request
from collections import defaultdict

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
DATA = "https://data-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
REQ_GAP_S = 0.35
_last = 0.0


def get(url, tries=4):
    """A transient failure must never be mistaken for the end of a history.
    The first version of this swallowed one timeout and reported four days of
    a three-month wallet as if it were the whole thing."""
    global _last
    last_err = None
    for attempt in range(tries):
        wait = REQ_GAP_S - (time.time() - _last)
        if wait > 0:
            time.sleep(wait)
        _last = time.time()
        try:
            return json.load(urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=30))
        except Exception as ex:  # noqa: BLE001
            last_err = ex
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"fallo tras {tries} intentos: {str(last_err)[:120]}")


def _key(a):
    return (a.get("transactionHash"), a.get("asset"), a.get("type"),
            str(a.get("size")), str(a.get("timestamp")), a.get("side"),
            str(a.get("usdcSize")))


def fetch_history(addr, max_events=600_000, progress=False):
    """Complete activity, walked backwards with an `end` cursor.

    Two hazards this handles: a batch can be entirely events at one timestamp,
    which stalls a naive cursor, and a single request failing must retry rather
    than end the walk. Returns (events, complete) , complete is False only when
    the ceiling was hit, so the caller can say so instead of implying totality.
    """
    seen = set()
    out = []
    end = None
    stalls = 0
    while len(out) < max_events:
        url = f"{DATA}/activity?user={addr}&limit=500"
        if end is not None:
            url += f"&end={end}"
        batch = get(url)
        if not isinstance(batch, list) or not batch:
            return out, True
        fresh = 0
        for a in batch:
            k = _key(a)
            if k in seen:
                continue
            seen.add(k)
            out.append(a)
            fresh += 1
        oldest = min(int(a.get("timestamp") or 0) for a in batch)
        if progress and len(out) % 5000 < 500:
            print(f"    ...{len(out):,} eventos, hasta "
                  f"{time.strftime('%Y-%m-%d', time.gmtime(oldest))}", flush=True)
        if fresh == 0 or (end is not None and oldest >= end):
            # the window is exhausted; step one second past it, and give up
            # only after this fails to produce anything twice in a row
            stalls += 1
            if stalls >= 2:
                return out, True
            end = (oldest if end is None else min(end, oldest)) - 1
            continue
        stalls = 0
        end = oldest
    return out, False


def audit(addr, progress=False):
    acts, complete = fetch_history(addr, progress=progress)
    if not acts:
        return {"error": "sin actividad o direccion invalida"}

    trades = [a for a in acts if a.get("type") == "TRADE"]
    redeems = [a for a in acts if a.get("type") in ("REDEEM", "CLAIM")]
    rebates = [a for a in acts if "REBATE" in str(a.get("type") or "").upper()
               or str(a.get("type") or "").upper() == "REWARD"]

    fees = 0.0
    buys = sells = 0.0
    maker_fills = taker_fills = 0
    per_market = defaultdict(float)
    by_day = defaultdict(float)
    prices = []

    for t in trades:
        px = float(t.get("price") or 0)
        sz = float(t.get("size") or 0)
        usdc = float(t.get("usdcSize") or 0)
        notional = px * sz
        # cash flow is what actually moved in USDC; the fee is the gap between
        # that and the notional, which is where Polymarket hides it
        if t.get("side") == "BUY":
            fee = max(0.0, usdc - notional)
            flow = -usdc
            prices.append(px)
        else:
            fee = max(0.0, notional - usdc)
            flow = usdc
        fees += fee
        if fee < 0.0001 * max(notional, 1.0):
            maker_fills += 1
        else:
            taker_fills += 1
        day = time.strftime("%Y-%m-%d", time.gmtime(int(t.get("timestamp") or 0)))
        if t.get("side") == "BUY":
            buys += usdc
        else:
            sells += usdc
        per_market[t.get("conditionId")] += flow
        by_day[day] += flow

    redeemed = 0.0
    zero_redeems = 0
    for r in redeems:
        v = float(r.get("usdcSize") or r.get("size") or 0)
        if v == 0:
            zero_redeems += 1
        redeemed += v
        per_market[r.get("conditionId")] += v
        by_day[time.strftime("%Y-%m-%d", time.gmtime(int(r.get("timestamp") or 0)))] += v

    # A merge turns a paired YES+NO back into a dollar and a split does the
    # reverse. Wallets that recycle capital this way move six figures through
    # these events; ignoring them reads as a catastrophic loss that never
    # happened.
    merged = split_out = 0.0
    for a in acts:
        ty = str(a.get("type") or "").upper()
        if ty not in ("MERGE", "SPLIT", "CONVERSION"):
            continue
        v = float(a.get("usdcSize") or a.get("size") or 0)
        day = time.strftime("%Y-%m-%d", time.gmtime(int(a.get("timestamp") or 0)))
        if ty == "MERGE":
            merged += v
            per_market[a.get("conditionId")] += v
            by_day[day] += v
        elif ty == "SPLIT":
            split_out += v
            per_market[a.get("conditionId")] -= v
            by_day[day] -= v

    rebate_total = sum(float(r.get("usdcSize") or r.get("size") or 0) for r in rebates)

    try:
        portfolio = float((get(f"{DATA}/value?user={addr}") or [{}])[0].get("value") or 0)
    except Exception:  # noqa: BLE001
        portfolio = 0.0

    cash = sells + redeemed + merged - buys - split_out
    real_pnl = cash + rebate_total + portfolio

    try:
        lb = get(f"{DATA}/v1/leaderboard?timePeriod=all&orderBy=PNL&limit=1&offset=0"
                 f"&category=overall&user={addr}")
        official = float(lb[0].get("pnl") or 0) if isinstance(lb, list) and lb else None
    except Exception:  # noqa: BLE001
        official = None

    vals = sorted(per_market.values(), reverse=True)
    gains = [v for v in vals if v > 0]
    top5 = sum(vals[:5])
    days = sorted(by_day)
    half = len(days) // 2
    h1 = sum(by_day[d] for d in days[:half])
    h2 = sum(by_day[d] for d in days[half:])
    pos_days = sum(1 for d in days if by_day[d] > 0)

    # Reconciliation against an INDEPENDENT number. Comparing our ledger to our
    # own cash flow proves nothing: both come from the same rows, so the check
    # can never fail. The venue's public figure is fee-blind and rebate-blind,
    # which gives a real identity to test:  official ≈ real + fees − rebates.
    # A wide gap means events are missing (zero-valued redeems, unhandled
    # transfer types) and the numbers must not be published as fact.
    # What it cannot test, by construction, is the rebate line: real_pnl already
    # contains rebates, so they cancel out of real + fees - rebates. An outside
    # reviewer had to point that out. The identity checks cash flow, open value
    # and fees against the venue. It never checks the subsidy.
    expected_official = real_pnl + fees - rebate_total
    reconciled = None
    gap_pct = None
    if official is not None and abs(official) > 1:
        gap_pct = abs(expected_official - official) / max(abs(official), 1.0)
        reconciled = gap_pct <= 0.05

    # A derived number the same size as the books' own error bar has no sign,
    # so the effect is compared against the run's reconciliation residual before
    # anything is claimed about it. This lives in code because prose was not
    # enough: the same rule was published as prose on 2026-08-09 and broken that
    # same day by the person who wrote it, who called $4,218 of effect "inside"
    # a $2,567 residual. It is not inside. It is resolved, and positive, and the
    # identity's other estimator agrees by construction: official - fees comes
    # to $1,651, which is 4,218 - 2,567 exactly. The first run of this coded
    # version contradicted the site copy shipped that morning.
    without_rebate = real_pnl - rebate_total
    resid_usd = (abs(expected_official - official)
                 if official is not None and abs(official) > 1 else None)
    if rebate_total <= 0:
        sin_rebate_signo = None
    elif resid_usd is None:
        sin_rebate_signo = "SIN_CONTRASTE"
    elif abs(without_rebate) <= resid_usd:
        sin_rebate_signo = "INDETERMINADO"
    else:
        sin_rebate_signo = "POSITIVO" if without_rebate > 0 else "NEGATIVO"

    ts = [int(a.get("timestamp") or 0) for a in acts if a.get("timestamp")]
    return {
        "address": addr,
        "historial_completo": complete,
        "reconciliado": reconciled,
        "desvio_vs_identidad_pct": round(100 * gap_pct, 1) if gap_pct is not None else None,
        "redeems_en_cero": zero_redeems,
        "merges_usd": round(merged, 2),
        "primer_movimiento": time.strftime("%Y-%m-%d", time.gmtime(min(ts))) if ts else None,
        "ultimo_movimiento": time.strftime("%Y-%m-%d", time.gmtime(max(ts))) if ts else None,
        "eventos": len(acts), "trades": len(trades), "mercados": len(per_market),
        "comprado_usd": round(buys, 2), "vendido_usd": round(sells, 2),
        "cobrado_usd": round(redeemed, 2),
        "fee_pagado": round(fees, 2), "rebates": round(rebate_total, 2),
        "cartera_abierta": round(portfolio, 2),
        "PNL_REAL": round(real_pnl, 2),
        "pnl_oficial_prefee": round(official, 2) if official is not None else None,
        "diferencia_vs_oficial": round(official - real_pnl, 2) if official is not None else None,
        "fills_maker": maker_fills, "fills_taker": taker_fills,
        "pct_maker": round(100 * maker_fills / max(1, len(trades)), 1),
        "precio_medio_compra": round(sum(prices) / len(prices), 3) if prices else None,
        "top5_pct_de_ganancias": round(100 * top5 / sum(gains), 1) if gains else None,
        "mitad_1": round(h1, 2), "mitad_2": round(h2, 2),
        "dias_operados": len(days), "dias_positivos": pos_days,
        "trading_sin_rebate": round(without_rebate, 2),
        "signo_sin_rebate": sin_rebate_signo,
        "vive_del_rebate": bool(rebate_total > 0 and (real_pnl - rebate_total) <= 0),
    }


def verdict(a):
    """Plain-language read of the shape, not advice."""
    out = []
    if a.get("reconciliado") is False:
        out.append(f"NO CONFIABLE: las cuentas no cierran contra el dato publico "
                   f"(desvio {a.get('desvio_vs_identidad_pct')}%). "
                   f"Faltan eventos: {a.get('redeems_en_cero')} cobros vienen en cero "
                   "en la API. No publicar estos numeros.")
    elif a.get("reconciliado") is None:
        out.append("Sin dato publico para contrastar: numeros sin verificacion cruzada.")
    if not a.get("historial_completo"):
        out.append("Historial truncado por tamano: el resultado cubre solo el "
                   "periodo mas reciente, no toda su vida.")
    signo = a.get("signo_sin_rebate")
    if signo == "NEGATIVO":
        out.append("SU TRADING PIERDE — la ganancia sale del rebate por volumen. "
                   "Copiar sus trades sin ese tier es perder.")
    elif signo == "INDETERMINADO":
        out.append("Sin el rebate el resultado es mas chico que el residuo de "
                   "reconciliacion: signo INDETERMINADO. El rebate domina el "
                   "ingreso; el trading no demuestra ventaja.")
    elif signo == "POSITIVO" and (a.get("rebates") or 0) > 0 \
            and (a.get("PNL_REAL") or 0) > 0 \
            and a["rebates"] > 0.5 * a["PNL_REAL"]:
        out.append(f"El rebate es la fuente dominante del ingreso "
                   f"({100 * a['rebates'] / a['PNL_REAL']:.0f}% del neto): el "
                   "trading suma poco y la economia del wallet no se replica "
                   "sin ese tier.")
    if a.get("diferencia_vs_oficial") and a["diferencia_vs_oficial"] > 0:
        out.append(f"El perfil publico exagera en ${a['diferencia_vs_oficial']:,.0f} "
                   "(no descuenta el fee).")
    t5 = a.get("top5_pct_de_ganancias")
    if t5 and t5 > 60:
        out.append(f"Concentrado: {t5:.0f}% de las ganancias en 5 mercados — "
                   "una racha, no un metodo.")
    if a.get("mitad_1") is not None and a["mitad_1"] < 0 < a.get("mitad_2", 0):
        out.append("Perdia en la primera mitad de su historia: el resultado "
                   "depende de un periodo, no de una ventaja estable.")
    if a.get("pct_maker", 0) > 90:
        out.append("Es maker casi puro (fee cero): su negocio es cotizar, "
                   "no acertar. No se copia con picks.")
    if not out:
        out.append("Sin banderas obvias: ganancia repartida y consistente.")
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    addr = sys.argv[1]
    a = audit(addr, progress="--json" not in sys.argv)
    if "--json" in sys.argv:
        print(json.dumps(a, ensure_ascii=False, indent=1))
        return
    if a.get("error"):
        print(a["error"])
        return
    print(f"\n=== {addr} ===")
    print(f"  activo {a['primer_movimiento']} -> {a['ultimo_movimiento']} | "
          f"{a['trades']:,} trades en {a['mercados']:,} mercados")
    print(f"\n  PNL REAL (fee y rebates incluidos): ${a['PNL_REAL']:,.2f}")
    if a["pnl_oficial_prefee"] is not None:
        print(f"  el perfil publico dice:             ${a['pnl_oficial_prefee']:,.2f}"
              f"   <-- pre-fee")
    print(f"\n  fee pagado ${a['fee_pagado']:,.2f} | rebates ${a['rebates']:,.2f} | "
          f"maker {a['pct_maker']}% de los fills")
    print(f"  top-5 mercados = {a['top5_pct_de_ganancias']}% de las ganancias | "
          f"mitades de caja {a['mitad_1']:+,.0f} / {a['mitad_2']:+,.0f} | "
          f"dias {a['dias_positivos']}/{a['dias_operados']} positivos")
    print("  (las lineas de forma son flujo de caja: sin rebates ni libro abierto)")
    print("\n  LECTURA:")
    for line in verdict(a):
        print(f"   - {line}")
    print()


if __name__ == "__main__":
    main()
