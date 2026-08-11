"""User's cell, pre-registered BEFORE results: maker fill at 0.80 on the
expensive side of BTC 5m candles — does it hold often enough to pay?

Universe: all btc-updown-5m candles of the last 48h (closed).
Entry proxy: the EXPENSIVE side = outcome whose last print reached >= 0.85
mid-window; fill = the first later print on that side with side==SELL and
price in [0.72, 0.80] within [60s, 270s] of window start (a taker selling
into resting bids at/through 0.80 = our maker fill). One entry per candle.
Win = that side's winner flag from CLOB.
Breakeven: entry ~0.78, salvage ~0.05 on losers -> p* ~= 0.77.
Caveats stated: tape timestamps are placement-time (documented gotcha);
side semantics = taker side; this proxies queue position optimistically
(assumes our bid was at the front) — reality is WORSE, so a negative
verdict is conservative and a positive one is an upper bound.
Report: n candles, n fills, hold rate + Wilson CI, avg entry, halves,
plus unconditional favorite-hold in the same sample for context.
"""
import json
import math
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
GAMMA = "https://gamma-api.polymarket.com/events?slug=btc-updown-5m-{}"
TRADES = "https://data-api.polymarket.com/trades?market={}&limit=500&offset={}"
CLOB = "https://clob.polymarket.com/markets/{}"
HOURS = 48


def get(url):
    time.sleep(0.28)
    try:
        return json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=20))
    except Exception:
        return None


def wilson(p, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    s = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - s) / d, (c + s) / d


def main():
    now = int(time.time())
    end = (now // 300) * 300 - 900          # margen: velas bien cerradas
    start = end - HOURS * 3600
    stamps = list(range(start, end, 300))
    print(f"velas objetivo: {len(stamps)} ({HOURS}h)")

    events = []            # (ts, entry_price, won)
    fav_hold = [0, 0]      # contexto: favorito a mitad de vela gano?
    scanned = 0
    for i, t0 in enumerate(stamps):
        ev = get(GAMMA.format(t0))
        if not ev:
            continue
        m = (ev[0].get("markets") or [{}])[0]
        cid = m.get("conditionId")
        if not cid:
            continue
        w = get(CLOB.format(cid))
        toks = (w or {}).get("tokens") or []
        winner = {x.get("outcome"): bool(x.get("winner")) for x in toks}
        if not any(winner.values()):
            continue
        trades = []
        for off in (0, 500, 1000, 1500):
            page = get(TRADES.format(cid, off))
            if not isinstance(page, list) or not page:
                break
            trades.extend(page)
            if len(page) < 500:
                break
        if not trades:
            continue
        trades.sort(key=lambda t: (t.get("timestamp") or 0))
        scanned += 1
        last = {}
        expensive_seen = {}
        entry = None
        mid_leader = None
        for t in trades:
            ts = int(t.get("timestamp") or 0)
            rel = ts - t0
            out = t.get("outcome")
            px = float(t.get("price") or 0)
            if rel < 0 or rel > 300:
                continue
            last[out] = px
            if 60 <= rel <= 270:
                if mid_leader is None and px >= 0.55:
                    mid_leader = out if px > 0.5 else None
                if px >= 0.85:
                    expensive_seen[out] = True
                if (entry is None and expensive_seen.get(out)
                        and t.get("side") == "SELL"
                        and 0.72 <= px <= 0.80):
                    entry = (out, px)
        if entry:
            events.append((t0, entry[1], winner.get(entry[0], False)))
        if mid_leader:
            fav_hold[0] += 1
            fav_hold[1] += winner.get(mid_leader, False)
        if (i + 1) % 100 == 0:
            print(f"  ...{i + 1} velas, fills {len(events)}", flush=True)

    n = len(events)
    print(f"\nvelas con cinta: {scanned} | fills-proxy 0.72-0.80: {n}")
    if not n:
        print("sin eventos — celda vacia")
        return
    wins = sum(1 for _, _, w in events if w)
    p = wins / n
    lo, hi = wilson(p, n)
    avg_e = sum(e for _, e, _ in events) / n
    h = n // 2
    p1 = sum(1 for _, _, w in events[:h] if w) / max(1, h)
    p2 = sum(1 for _, _, w in events[h:] if w) / max(1, n - h)
    ev_net = p * (1 - avg_e) - (1 - p) * (avg_e - 0.05)
    print(f"HOLD del fill a 0.80: {100 * p:.1f}%  (IC95 {100 * lo:.1f}-"
          f"{100 * hi:.1f})  | breakeven ~77%")
    print(f"entrada media {avg_e:.3f} | mitades {100 * p1:.0f}%/{100 * p2:.0f}%")
    print(f"EV neto por trade (salvage 5c): {100 * ev_net:+.1f}c por share")
    if fav_hold[0]:
        print(f"contexto: favorito de mitad de vela gano "
              f"{100 * fav_hold[1] / fav_hold[0]:.1f}% de {fav_hold[0]} velas")


if __name__ == "__main__":
    main()
