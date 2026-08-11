"""Pump study — small Binance USDT pairs, pre-registered.

Question: after a detectable pump (1h candle >= +10% / +5%), what does the
FIRST honest entry (close of the trigger candle, fee 0.2% RT) earn at
+1h, +4h, +24h? Also: how big was the run-up you'd have needed to PREDICT
(return from 24h before trigger to trigger close), and how often pumps
happen across the universe.

Universe: spot USDT pairs ranked ~31-130 by 24h quote volume (small but
tradeable), current listing only — survivorship makes results look BETTER
than reality (delisted pumpers are gone), so a negative verdict is
conservative. Cooldown: one event per pair per 24h.
"""
import json
import math
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
DAYS = 90
FEE_RT = 0.002
COOLDOWN = 24


def get(url):
    time.sleep(0.25)
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=30))


def universe():
    ticks = get("https://api.binance.com/api/v3/ticker/24hr")
    usdt = [t for t in ticks if t["symbol"].endswith("USDT")
            and float(t.get("quoteVolume") or 0) > 0
            and not any(x in t["symbol"] for x in
                        ("UP", "DOWN", "BULL", "BEAR", "USDC", "FDUSD",
                         "TUSD", "EUR", "DAI"))]
    usdt.sort(key=lambda t: -float(t["quoteVolume"]))
    return [t["symbol"] for t in usdt[30:130]]


def fetch_1h(symbol):
    need = DAYS * 24
    out = []
    end = None
    while len(out) < need:
        url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}"
               f"&interval=1h&limit=1000")
        if end:
            url += f"&endTime={end}"
        try:
            batch = get(url)
        except Exception:
            return []
        if not batch:
            break
        out = batch + out
        if len(batch) < 1000:
            break
        end = batch[0][0] - 1
    return [float(k[4]) for k in out[-need:]]


def stats(rets):
    n = len(rets)
    if n < 2:
        return n, 0.0, 0.0, 0.0
    mu = sum(rets) / n
    var = sum((r - mu) ** 2 for r in rets) / (n - 1)
    t = mu / math.sqrt(var / n) if var > 0 else 0.0
    wr = sum(1 for r in rets if r > 0) / n
    return n, mu, t, wr


def main():
    syms = universe()
    print(f"universo: {len(syms)} pares (ranks 31-130 por volumen 24h)")
    events = {0.10: [], 0.05: []}
    total_hours = 0
    for si, sym in enumerate(syms):
        closes = fetch_1h(sym)
        if len(closes) < 200:
            continue
        total_hours += len(closes)
        for T in events:
            last_i = -10**9
            for i in range(25, len(closes) - 24):
                r = closes[i] / closes[i - 1] - 1
                if r >= T and i - last_i >= COOLDOWN:
                    last_i = i
                    runup = closes[i] / closes[i - 24] - 1
                    f1 = closes[i + 1] / closes[i] - 1 - FEE_RT
                    f4 = closes[i + 4] / closes[i] - 1 - FEE_RT
                    f24 = closes[i + 24] / closes[i] - 1 - FEE_RT
                    events[T].append((i, runup, f1, f4, f24))
        if (si + 1) % 25 == 0:
            print(f"  ...{si + 1} pares", flush=True)

    weeks = total_hours / 24 / 7 / max(1, len(syms)) * len(syms)
    for T, evs in events.items():
        evs.sort(key=lambda e: e[0])
        n = len(evs)
        per_week = n / (DAYS / 7)
        print(f"\n=== pump >= +{T:.0%} en 1h | eventos: {n} "
              f"(~{per_week:.0f}/semana en el universo) ===")
        if not n:
            continue
        ru = sorted(e[1] for e in evs)
        print(f"  run-up previo 24h (lo que habia que PREDECIR): "
              f"mediana {100 * ru[n // 2]:+.1f}%")
        for label, idx in (("+1h", 2), ("+4h", 3), ("+24h", 4)):
            rets = [e[idx] for e in evs]
            nn, mu, t, wr = stats(rets)
            h = nn // 2
            h1 = sum(rets[:h]) / max(1, h)
            h2 = sum(rets[h:]) / max(1, nn - h)
            med = sorted(rets)[nn // 2]
            print(f"  {label:>4}: neto medio {100 * mu:+.2f}% | mediana "
                  f"{100 * med:+.2f}% | t {t:+.2f} | WR {100 * wr:.0f}% | "
                  f"mitades {100 * h1:+.2f}%/{100 * h2:+.2f}%")


if __name__ == "__main__":
    main()
