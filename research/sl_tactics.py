"""Take-profit + stop-loss tactics on BTC — does the SL fix the grid?

Pre-registered pairs (TP, SL): (2%,1%), (2%,2%), (5%,2%), (1%,1%).
Rule: whenever flat, buy at 1h close; exit at the first close >= entry*(1+TP)
or <= entry*(1-SL); fee 0.2% per round trip; re-enter immediately.
Exits on CLOSES (no intrabar guess — conservative and unambiguous).
Report: trades, win rate, realized total, final mark-to-market TOTAL,
fees paid, vs buy&hold and vs the no-stop version.
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
    return [float(k[4]) for k in out[-need:]]


def run(closes, tp, sl):
    equity = 1.0
    entry = None
    wins = losses = 0
    fees = 0.0
    for c in closes:
        if entry is None:
            entry = c
            continue
        if c >= entry * (1 + tp):
            equity *= (c / entry) * (1 - FEE_RT)
            fees += FEE_RT
            wins += 1
            entry = c
        elif c <= entry * (1 - sl):
            equity *= (c / entry) * (1 - FEE_RT)
            fees += FEE_RT
            losses += 1
            entry = c
    open_pnl = closes[-1] / entry - 1 if entry else 0.0
    total = equity * (1 + open_pnl) - 1
    return wins, losses, fees, total


def main():
    closes = fetch_1h("BTCUSDT", 365)
    bh = closes[-1] / closes[0] - 1
    print(f"BTC 365d | buy&hold {100 * bh:+.1f}% | "
          f"sin-stop (medido antes): -45.1%\n")
    print(f"{'TP':>4} {'SL':>4} {'trades':>7} {'WR':>5} "
          f"{'fees pagados':>13} {'TOTAL anio':>11}")
    for tp, sl in ((0.02, 0.01), (0.02, 0.02), (0.05, 0.02), (0.01, 0.01)):
        w, l, fees, total = run(closes, tp, sl)
        n = w + l
        wr = 100 * w / n if n else 0
        print(f"{tp:>4.0%} {sl:>4.0%} {n:>7} {wr:>4.0f}% "
              f"{100 * fees:>12.1f}% {100 * total:>10.1f}%")


if __name__ == "__main__":
    main()
