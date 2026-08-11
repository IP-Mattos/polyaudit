"""'Buy, take +X%, repeat' on BTC — the grid intuition, honestly accounted.

Rule (pre-registered): whenever flat, buy at the 1h close; sell when a
close >= entry*(1+X); fee 0.2% per round trip. No stop (the user's version
has none). X in {2%, 5%}. At year end the open position is marked to
market — the bag is part of the result, not a footnote.
Report: closed clips (count, win rate, realized P&L), open-bag P&L, TOTAL,
max drawdown, longest underwater stretch, vs buy & hold. Plus the actual
price path (was BTC really '60-65k constantly'?).
"""
import json
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
FEE_RT = 0.002


def get(url):
    time.sleep(0.25)
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=30))


def fetch_1h(symbol, days):
    need = days * 24
    out = []
    end = None
    while len(out) < need:
        url = (f"https://api.binance.com/api/v3/klines?symbol={symbol}"
               f"&interval=1h&limit=1000")
        if end:
            url += f"&endTime={end}"
        batch = get(url)
        if not batch:
            break
        out = batch + out
        end = batch[0][0] - 1
    return out[-need:]


def run(closes, x):
    equity = 1.0
    curve = []
    entry = None
    clips = 0
    realized = 0.0
    for c in closes:
        if entry is None:
            entry = c
        elif c >= entry * (1 + x):
            gain = c / entry - 1 - FEE_RT
            equity *= 1 + gain
            realized += gain
            clips += 1
            entry = c  # re-entra al toque (siempre comprado, como el grid)
        curve.append(equity * (c / entry if entry else 1))
    open_pnl = closes[-1] / entry - 1 if entry else 0.0
    total = equity * (1 + open_pnl) - 1
    # drawdown de la curva marcada a mercado
    peak = -1e9
    mdd = 0.0
    under = longest = 0
    for v in curve:
        if v > peak:
            peak = v
            under = 0
        else:
            under += 1
            longest = max(longest, under)
        mdd = max(mdd, 1 - v / peak)
    return clips, realized, open_pnl, total, mdd, longest


def main():
    k = fetch_1h("BTCUSDT", 365)
    closes = [float(x[4]) for x in k]
    highs = [float(x[2]) for x in k]
    lows = [float(x[3]) for x in k]
    bh = closes[-1] / closes[0] - 1
    print(f"BTC ultimos 365d: min ${min(lows):,.0f} | max ${max(highs):,.0f} "
          f"| hoy ${closes[-1]:,.0f} | buy&hold {100 * bh:+.1f}%")
    for x in (0.02, 0.05):
        clips, realized, open_pnl, total, mdd, longest = run(closes, x)
        print(f"\n--- tomar ganancia +{x:.0%}, sin stop ---")
        print(f"  trades CERRADOS: {clips} | todos ganadores | "
              f"suma realizada {100 * realized:+.1f}%")
        print(f"  la BOLSA abierta al final: {100 * open_pnl:+.1f}%")
        print(f"  TOTAL real del anio: {100 * total:+.1f}% "
              f"(vs buy&hold {100 * bh:+.1f}%)")
        print(f"  max drawdown {100 * mdd:.1f}% | "
              f"racha bajo agua mas larga: {longest / 24:.0f} dias")


if __name__ == "__main__":
    main()
