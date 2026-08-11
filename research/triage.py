"""Fast forensic triage of leaderboard wallets — fingerprint, not full audit.

Per wallet: official pnl + most-recent ~2,000 activity events ->
style fingerprint: span, event mix, maker share (fee-gap test), buy price
band, median clip, dominant market family, buys-vs-redeems cash.
"""
import json
import sys
import time
import urllib.request
from collections import Counter

UA = {"User-Agent": "Mozilla/5.0"}


def get(url):
    time.sleep(0.35)
    try:
        return json.load(urllib.request.urlopen(
            urllib.request.Request(url, headers=UA), timeout=25))
    except Exception:
        return None


def family(title):
    t = (title or "").lower()
    if "up or down" in t or "arriba o abajo" in t:
        if "5m" in t or ":" in t:
            return "updown"
        return "updown"
    for k, f in (("bitcoin", "crypto"), ("btc", "crypto"), ("ethereum",
                 "crypto"), ("nfl", "sports"),
                 ("nba", "sports"), ("mlb", "sports"), ("vs", "sports"),
                 ("election", "politics"), ("trump", "politics"),
                 ("fed", "macro"), ("tweet", "count")):
        if k in t:
            return f
    return "otros"


def triage(addr, label):
    lb = get(f"https://data-api.polymarket.com/v1/leaderboard?timePeriod=all"
             f"&orderBy=PNL&limit=1&offset=0&category=overall&user={addr}")
    official = None
    if isinstance(lb, list) and lb:
        official = float(lb[0].get("pnl") or 0)
    acts = []
    end = None
    for _ in range(4):
        url = f"https://data-api.polymarket.com/activity?user={addr}&limit=500"
        if end:
            url += f"&end={end}"
        batch = get(url)
        if not isinstance(batch, list) or not batch:
            break
        acts.extend(batch)
        if len(batch) < 500:
            break
        end = min(int(a.get("timestamp") or 0) for a in batch) - 1
    if not acts:
        print(f"{label:24} | SIN ACTIVIDAD (addr {addr[:10]}...)")
        return
    ts = [int(a.get("timestamp") or 0) for a in acts if a.get("timestamp")]
    span_d = (max(ts) - min(ts)) / 86400 if ts else 0
    trades = [a for a in acts if a.get("type") == "TRADE"]
    buys = [t for t in trades if t.get("side") == "BUY"]
    sells = [t for t in trades if t.get("side") == "SELL"]
    redeems = [a for a in acts if a.get("type") in ("REDEEM", "CLAIM")]
    maker = taker = 0
    fee = 0.0
    for t in trades:
        px = float(t.get("price") or 0)
        sz = float(t.get("size") or 0)
        usdc = float(t.get("usdcSize") or 0)
        notional = px * sz
        gap = (usdc - notional) if t.get("side") == "BUY" else (notional - usdc)
        fee += max(0.0, gap)
        if gap < 0.0001 * max(notional, 1.0):
            maker += 1
        else:
            taker += 1
    bpx = sorted(float(t.get("price") or 0) for t in buys)
    med_px = bpx[len(bpx) // 2] if bpx else 0
    sizes = sorted(float(t.get("usdcSize") or 0) for t in trades)
    med_sz = sizes[len(sizes) // 2] if sizes else 0
    fams = Counter(family(a.get("title")) for a in trades)
    top_fam = ", ".join(f"{k}:{v}" for k, v in fams.most_common(2))
    buy_usd = sum(float(t.get("usdcSize") or 0) for t in buys)
    red_usd = sum(float(r.get("usdcSize") or r.get("size") or 0)
                  for r in redeems)
    per_day = len(trades) / max(span_d, 0.01)
    print(f"{label:24} | pnl_oficial "
          f"{'?' if official is None else f'{official:>+10,.0f}'} | "
          f"muestra {len(acts):>4}ev/{span_d:>5.1f}d (~{per_day:>5.0f} tr/d) | "
          f"maker {100 * maker / max(1, maker + taker):>3.0f}% | "
          f"px_med_compra {med_px:.2f} | clip_med ${med_sz:,.0f} | "
          f"fee_muestra ${fee:,.0f} | buys ${buy_usd:,.0f} vs "
          f"redeems ${red_usd:,.0f} | {top_fam}")


def main():
    wallets = json.loads(sys.argv[1])
    print(f"{'wallet':24} | fingerprint")
    for label, addr in wallets.items():
        triage(addr, label)


if __name__ == "__main__":
    main()
