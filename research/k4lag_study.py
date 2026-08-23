#!/usr/bin/env python3
"""What is actually in the k4lag: does the latency edge survive, and at what delay?

k4lag is a different animal from everything else on this desk. It is not "who is
ahead on spot-vs-strike" — it is `binance_up_poly_lag_oracle_safe`: Binance moves
and the Polymarket book has not repriced yet. Two things follow. Using Binance is
CORRECT here (you want the fast feed to see the move first), and it has always
read the real CLOB book, so its numbers were never poisoned by the und_tracker
lag that voided everything else today.

It also ran a controlled experiment for us: 3236 arm-settles across four posting
delays (350/500/700/1000ms), with no-fills booked at zero. That is the decay
curve of a latency edge, measured on our own tape.
"""
import os
import collections
import json
import math

LOG = os.environ.get("K4LAG_LOG", "data/k4lag_live.jsonl")


def stats(rows, name, pnl_key="pnl"):
    """Per-OPPORTUNITY economics: non-fills count as zero, never dropped."""
    if len(rows) < 25:
        print("  %-30s n=%-5d (pocos)" % (name, len(rows)))
        return None
    per = [float(r.get(pnl_key) or 0.0) for r in rows]
    n = len(per)
    mu = sum(per) / n
    sd = (sum((x - mu) ** 2 for x in per) / max(1, n - 1)) ** 0.5
    t = mu / (sd / math.sqrt(n)) if sd > 0 else 0.0
    fills = sum(1 for r in rows if r.get("bet") or (r.get("shares") or 0))
    wins = sum(1 for r in rows if r.get("won") or r.get("market_won") is True and (r.get("bet") or r.get("shares")))
    k = n // 2
    h1 = sum(per[:k]) / max(1, k)
    h2 = sum(per[k:]) / max(1, n - k)
    print("  %-30s n=%-5d fill=%3.0f%% PnL/oport=%+.4f total=%+8.2f t=%+6.2f mitades %+.4f/%+.4f %s"
          % (name, n, 100.0 * fills / n, mu, sum(per), t, h1, h2,
             "OK" if (h1 > 0 and h2 > 0) else ""))
    return mu


def main():
    arms = []
    shadow = []
    live = []
    signals = {}
    for line in open(LOG, errors="ignore"):
        if '"K4LL_' not in line:
            continue
        try:
            o = json.loads(line)
        except Exception:
            continue
        t = o.get("t")
        if t == "K4LL_SHADOW_ARM_SETTLE":
            arms.append(o)
        elif t == "K4LL_SHADOW_SETTLE":
            shadow.append(o)
        elif t == "K4LL_SETTLE":
            live.append(o)
        elif t == "K4LL_SIGNAL":
            signals[o.get("slug")] = o
    arms.sort(key=lambda r: r.get("ts") or 0)
    shadow.sort(key=lambda r: r.get("ts") or 0)
    live.sort(key=lambda r: r.get("ts") or 0)
    print("  arm-settles=%d  shadow=%d  live=%d  senales=%d\n"
          % (len(arms), len(shadow), len(live), len(signals)), flush=True)

    print("=" * 108)
    print("1) LA CURVA DE DECAIMIENTO: cuanto edge sobrevive a cada demora de posteo")
    print("=" * 108)
    by_arm = collections.defaultdict(list)
    for r in arms:
        by_arm[r.get("arm") or str(r.get("delay_ms"))].append(r)
    for arm in sorted(by_arm, key=lambda a: int(str(a).replace("ms", "") or 0)):
        stats(by_arm[arm], "demora %s" % arm)

    print()
    print("=" * 108)
    print("2) POR QUE NO LLENA  (el no-fill es la mitad del negocio)")
    print("=" * 108)
    reasons = collections.Counter(r.get("reason") or "-" for r in arms
                                  if not (r.get("bet") or r.get("shares")))
    tot_nf = sum(reasons.values())
    print("  no-fills: %d de %d (%.0f%%)" % (tot_nf, len(arms), 100.0 * tot_nf / max(1, len(arms))))
    for reason, c in reasons.most_common(8):
        print("    %-28s %5d (%.0f%% de los no-fills)" % (reason, c, 100.0 * c / max(1, tot_nf)))

    print()
    print("=" * 108)
    print("3) EL BRAZO MAS RAPIDO, PARTIDO  (donde vive o muere)")
    print("=" * 108)
    fast = by_arm.get("350ms") or []
    if fast:
        stats(fast, "350ms TODO")
        stats([r for r in fast if r.get("bet") or r.get("shares")], "350ms solo llenadas")
        for a in ("btc", "eth"):
            stats([r for r in fast if r.get("asset") == a], "350ms " + a.upper())
        for s in ("up", "down"):
            stats([r for r in fast if r.get("side") == s], "350ms " + s.upper())

    print()
    print("=" * 108)
    print("4) POR TAMANO DEL SALTO DE BINANCE (move_bps de la senal)")
    print("=" * 108)
    tagged = []
    for r in fast:
        sig = signals.get(r.get("slug"))
        if not sig:
            continue
        try:
            mv = abs(float(sig.get("move_bps")))
        except (TypeError, ValueError):
            continue
        rr = dict(r)
        rr["move_bps"] = mv
        tagged.append(rr)
    print("  con move_bps: %d" % len(tagged))
    for lo, hi, lbl in ((0, 2, "<2 bps"), (2, 4, "2-4 bps"),
                        (4, 8, "4-8 bps"), (8, 1e9, ">8 bps")):
        stats([r for r in tagged if lo <= r["move_bps"] < hi], "salto " + lbl)

    print()
    print("=" * 108)
    print("5) EL SHADOW Y EL LIVE DE VERDAD")
    print("=" * 108)
    if shadow:
        stats(shadow, "shadow (todas)")
        n = len(shadow)
        w = sum(1 for r in shadow if r.get("won"))
        print("     WR=%.3f  costo medio=%.3f  fee total=%.2f"
              % (w / n,
                 sum(float(r.get("cost") or 0) for r in shadow) / max(1, sum(float(r.get("shares") or 0) for r in shadow)),
                 sum(float(r.get("fee") or 0) for r in shadow)))
    if live:
        print()
        print("  LIVE (plata real): %d settles" % len(live))
        for r in live[-8:]:
            print("    %s %-4s %-4s gano=%-5s shares=%-8s costo=%-6s pnl=%+.4f"
                  % (r.get("slug", "")[-14:], r.get("asset"), r.get("side"),
                     r.get("won"), r.get("shares"), r.get("cost"), float(r.get("pnl") or 0)))
        tot = sum(float(r.get("pnl") or 0) for r in live)
        print("    TOTAL REAL: %+.4f en %d operaciones" % (tot, len(live)))


if __name__ == "__main__":
    main()
