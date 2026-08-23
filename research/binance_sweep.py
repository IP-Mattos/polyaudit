"""Pre-registered Binance intraday sweep: fees in, both halves, no tuning.

Rules FIXED before seeing any result (registered in this docstring):
  R-MOM: candle t closes beyond +T% -> buy at close(t), exit close(t+1).
  R-REV: candle t closes beyond -T% -> buy at close(t), exit close(t+1).
  R-BRK: close(t) > max(high[t-20..t-1]) -> buy close(t), exit close(t+4).
  Thresholds T per timeframe (a priori): 15m 0.3% | 1h 0.6% | 4h 1.2% | 1d 2.0%.
  Fee: 0.2% round trip (0.1%/side spot taker). Long only (spot).
  Benchmark: buy & hold over the same period.
Verdict bar (all required): net mean > 0, |t| >= 2, both halves same sign,
and the SAME cell must also pass on the control asset (ETH).
"""
import json
import math
import time
import urllib.request

BASE = "https://api.binance.com/api/v3/klines"
UA = {"User-Agent": "Mozilla/5.0"}
DAYS = 365
FEE_RT = 0.002
THRESH = {"15m": 0.003, "1h": 0.006, "4h": 0.012, "1d": 0.02}
CANDLES_PER_DAY = {"15m": 96, "1h": 24, "4h": 6, "1d": 1}


def get(url):
    time.sleep(0.25)
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=30))


def fetch(symbol, interval):
    need = DAYS * CANDLES_PER_DAY[interval]
    out = []
    end = None
    while len(out) < need:
        url = f"{BASE}?symbol={symbol}&interval={interval}&limit=1000"
        if end:
            url += f"&endTime={end}"
        batch = get(url)
        if not batch:
            break
        out = batch + out
        end = batch[0][0] - 1
    out = out[-need:]
    # close-to-close returns; also keep highs for breakout
    closes = [float(k[4]) for k in out]
    highs = [float(k[2]) for k in out]
    return closes, highs


def stats(rets):
    n = len(rets)
    if n < 2:
        return n, 0.0, 0.0
    mu = sum(rets) / n
    var = sum((r - mu) ** 2 for r in rets) / (n - 1)
    t = mu / math.sqrt(var / n) if var > 0 else 0.0
    return n, mu, t


def halves(trades):
    h = len(trades) // 2
    a = sum(r for _, r in trades[:h])
    b = sum(r for _, r in trades[h:])
    return a, b


def run(symbol, interval, closes, highs):
    T = THRESH[interval]
    rows = []
    mom, rev, brk = [], [], []
    for i in range(21, len(closes) - 4):
        r_prev = closes[i] / closes[i - 1] - 1
        nxt = closes[i + 1] / closes[i] - 1 - FEE_RT
        if r_prev >= T:
            mom.append((i, nxt))
        if r_prev <= -T:
            rev.append((i, nxt))
        if closes[i] > max(highs[i - 20:i]):
            brk.append((i, closes[i + 4] / closes[i] - 1 - FEE_RT))
    bh = closes[-1] / closes[21] - 1
    for name, trades in (("MOM", mom), ("REV", rev), ("BRK", brk)):
        n, mu, t = stats([r for _, r in trades])
        h1, h2 = halves(trades) if n >= 4 else (0.0, 0.0)
        rows.append((symbol, interval, name, n, mu, t, h1, h2))
    return rows, bh


def main():
    all_rows = []
    bh_map = {}
    for sym in ("BTCUSDT", "ETHUSDT"):
        for tf in ("15m", "1h", "4h", "1d"):
            closes, highs = fetch(sym, tf)
            rows, bh = run(sym, tf, closes, highs)
            all_rows.extend(rows)
            bh_map[(sym, tf)] = (bh, len(closes))
    print(f"{'sym':8} {'tf':4} {'regla':5} {'n':>6} {'neto/trade':>11} "
          f"{'t':>7} {'mitad1':>8} {'mitad2':>8}  veredicto")
    for sym, tf, name, n, mu, t, h1, h2 in all_rows:
        alive = (mu > 0 and abs(t) >= 2 and h1 > 0 and h2 > 0)
        v = "VIVA?" if alive else ("sangra" if mu < 0 else "ruido")
        print(f"{sym:8} {tf:4} {name:5} {n:>6} {100 * mu:>10.3f}% "
              f"{t:>7.2f} {100 * h1:>7.1f}% {100 * h2:>7.1f}%  {v}")
    print("\nbuy&hold del periodo:")
    for (sym, tf), (bh, nc) in bh_map.items():
        if tf == "1d":
            print(f"  {sym}: {100 * bh:+.1f}% ({nc} velas)")


if __name__ == "__main__":
    main()
