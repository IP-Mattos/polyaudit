"""New-listing dream vs reality: Binance USDT listings of the last year.

For each pair whose FIRST daily candle is between 365 and 31 days old:
  entry   = close of listing day 1 (first executable daily close)
  DREAM   = max(high of days 2..31) / entry - 1   (sell the exact top)
  REALITY = close of day 31 / entry - 1 - 0.2% RT (what you take home)
Also: day on which the peak occurred, and how many ever traded +20/+50/+100%.
Universe is Binance survivors, the BEST-case new coins (DEX launches and
presales are strictly worse: rugs and insider dumps are not in this data).
"""
import json
import math
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
FEE_RT = 0.002
NOW_MS = None


def get(url):
    time.sleep(0.25)
    return json.load(urllib.request.urlopen(
        urllib.request.Request(url, headers=UA), timeout=30))


def main():
    global NOW_MS
    NOW_MS = get("https://api.binance.com/api/v3/time")["serverTime"]
    info = get("https://api.binance.com/api/v3/exchangeInfo")
    syms = [s["symbol"] for s in info["symbols"]
            if s["quoteAsset"] == "USDT" and s["status"] == "TRADING"
            and s["isSpotTradingAllowed"]
            and not any(x in s["symbol"] for x in
                        ("UP", "DOWN", "BULL", "BEAR", "USDC", "FDUSD",
                         "TUSD", "EUR", "DAI", "WBTC", "WBETH"))]
    print(f"pares USDT spot activos: {len(syms)} — buscando listados "
          "de los ultimos 12 meses...")
    day = 86400 * 1000
    year_ago = NOW_MS - 365 * day
    month_ago = NOW_MS - 31 * day
    fresh = []
    for i, s in enumerate(syms):
        try:
            k = get(f"https://api.binance.com/api/v3/klines?symbol={s}"
                    f"&interval=1d&startTime=0&limit=1")
        except Exception:
            continue
        if k and year_ago <= k[0][0] <= month_ago:
            fresh.append((s, k[0][0]))
        if (i + 1) % 100 == 0:
            print(f"  ...{i + 1} chequeados, {len(fresh)} nuevos",
                  flush=True)
    print(f"listados en la ventana [365d, 31d]: {len(fresh)}")

    dreams, reals, peak_days = [], [], []
    ever20 = ever50 = ever100 = pos30 = 0
    for s, t0 in fresh:
        try:
            k = get(f"https://api.binance.com/api/v3/klines?symbol={s}"
                    f"&interval=1d&startTime={t0}&limit=31")
        except Exception:
            continue
        if len(k) < 31:
            continue
        entry = float(k[0][4])
        if entry <= 0:
            continue
        highs = [float(x[2]) for x in k[1:]]
        peak = max(highs)
        pday = highs.index(peak) + 2
        dream = peak / entry - 1
        real = float(k[30][4]) / entry - 1 - FEE_RT
        dreams.append(dream)
        reals.append(real)
        peak_days.append(pday)
        ever20 += dream >= 0.20
        ever50 += dream >= 0.50
        ever100 += dream >= 1.00
        pos30 += real > 0

    n = len(reals)
    if not n:
        print("sin datos suficientes")
        return
    dreams.sort()
    reals.sort()
    peak_days.sort()
    mean_r = sum(reals) / n
    print(f"\n=== {n} monedas nuevas (Binance, ya sobrevivientes) ===")
    print(f"EL SUENIO (vender el pico exacto de d2-d31):")
    print(f"  mediana {100 * dreams[n // 2]:+.1f}% | "
          f"tocaron +20%: {ever20}/{n} | +50%: {ever50}/{n} | "
          f"+100%: {ever100}/{n}")
    print(f"  dia mediano del pico: d{peak_days[n // 2]} "
          f"(a partir de cuando ya es tarde)")
    print(f"LA REALIDAD (lo que te llevas al dia 30, con fee):")
    print(f"  mediana {100 * reals[n // 2]:+.1f}% | media {100 * mean_r:+.1f}% | "
          f"terminan positivas: {pos30}/{n} ({100 * pos30 / n:.0f}%)")


if __name__ == "__main__":
    main()
