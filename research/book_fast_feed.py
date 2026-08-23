#!/usr/bin/env python3
"""Low-latency Polymarket book feed for the K4LAG detector.

Replaces the detector's dependency on the 1 Hz und-tracker snapshots WITHOUT
touching the Rust tracker: maintains live L2 books for the current and next
5m btc/eth up/down markets over the CLOB market WebSocket and appends
und-compatible snap rows to data/book_fast.jsonl (src="book_fast").

Key properties:
  * deterministic slugs ({asset}-updown-5m-{start}, start % 300 == 0) with
    token prefetch 60s before each window opens -> zero rollover latency;
  * both tokens per market subscribed (fav/und synthesis needs both sides);
  * strike = Chainlink price at cycle start, tailed from the basis feed
    (same source the market's own resolution uses);
  * read-only market data: no keys, no orders.
"""
import asyncio
import collections
import json
import os
import time
import urllib.request

import websockets

OUT = os.environ.get("BOOK_FAST_OUT", "data/book_fast.jsonl")
BASIS = os.environ.get("BASIS_FEED", "data/basis_feed.jsonl")
WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
GAMMA = "https://gamma-api.polymarket.com/markets?slug=%s"
ASSETS = ("btc", "eth", "sol", "xrp")
# Chainlink feed symbol -> asset. Must cover every entry in ASSETS: an asset
# missing here yields snaps with strike=None and spot=None, which are useless
# downstream (the whole edge is spot-vs-strike). Keep both lists in step.
CL_SYMBOL = {"%s/usd" % a: a for a in ASSETS}
WINDOW_S = 300
PREFETCH_LEAD_S = 60
TOKEN_RETRY_S = 3.0
EMIT_MAX_INTERVAL_S = 0.5
L2_DEPTH = 5
ROTATE_BYTES = 250 * 1024 * 1024
ROTATE_KEEP_S = 48 * 3600

markets = {}          # slug -> {asset, start, up, down}
books = {}            # token -> {"bids": {px: sz}, "asks": {px: sz}, "init": bool, "ts": float}
chain_px = {}         # asset -> (ts, px) latest chainlink observation
chain_hist = {}       # asset -> deque of (ts, px), for strike-at-cycle-start lookup
strikes = {}          # slug -> chainlink px at cycle start (None = window passed unseeded)
token_retry_after = {}
sub_queue = None      # asyncio.Queue of ("subscribe"|"unsubscribe", set(tokens))
n_rows = 0
BOOK_SRC_MAX_AGE_S = 3.0   # suppress emission when neither side saw a WS event this recently
STRIKE_WINDOW_S = 3.0      # chainlink obs must fall in [start-3, start+0.5] to seed the strike


def log_meta(obj):
    obj["ts"] = round(time.time(), 3)
    print(json.dumps(obj, separators=(",", ":")), flush=True)


def rotate_if_needed():
    try:
        if os.path.getsize(OUT) >= ROTATE_BYTES:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            os.replace(OUT, OUT + "." + stamp)
        base = os.path.basename(OUT) + "."
        folder = os.path.dirname(OUT)
        for name in os.listdir(folder):
            suffix = name[len(base):]
            if name.startswith(base) and suffix.startswith("20") and suffix.endswith("Z"):
                path = os.path.join(folder, name)
                if time.time() - os.path.getmtime(path) > ROTATE_KEEP_S:
                    os.remove(path)
    except FileNotFoundError:
        pass
    except Exception:
        pass


def fetch_tokens(slug):
    """Resolve (up_token, down_token) for a slug via gamma. Returns None on failure."""
    try:
        req = urllib.request.Request(GAMMA % slug, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8", "ignore"))
    except Exception:
        return None
    market = payload[0] if isinstance(payload, list) and payload else payload
    if not isinstance(market, dict):
        return None
    try:
        outcomes = json.loads(market.get("outcomes") or "[]")
        tokens = json.loads(market.get("clobTokenIds") or "[]")
    except Exception:
        return None
    if len(outcomes) != 2 or len(tokens) != 2:
        return None
    pair = {str(outcomes[i]).strip().lower(): str(tokens[i]) for i in range(2)}
    if "up" not in pair or "down" not in pair:
        return None
    return pair["up"], pair["down"]


def window_slugs(now):
    """Current window always; next window only inside the prefetch lead."""
    start = int(now // WINDOW_S) * WINDOW_S
    for asset in ASSETS:
        yield asset, start, "%s-updown-5m-%d" % (asset, start)
        nxt = start + WINDOW_S
        if nxt - now <= PREFETCH_LEAD_S:
            yield asset, nxt, "%s-updown-5m-%d" % (asset, nxt)


def resolve_strike(slug, start, now):
    """Chainlink px at cycle start, set once; None once the seed window passed."""
    if slug in strikes:
        return strikes[slug]
    asset = slug.split("-", 1)[0]
    best = None
    for ts, px in chain_hist.get(asset) or ():
        if start - STRIKE_WINDOW_S <= ts <= start + 0.5:
            if best is None or ts > best[0]:
                best = (ts, px)
    if best is not None:
        strikes[slug] = best[1]
        return best[1]
    if now - start > 5.0:
        strikes[slug] = None
    return None


async def market_manager():
    """Keep current+next window tokens resolved and the WS subscription set fresh."""
    loop = asyncio.get_running_loop()
    while True:
        now = time.time()
        for asset, start, slug in window_slugs(now):
            if slug in markets:
                continue
            if now < token_retry_after.get(slug, 0.0):
                continue
            pair = await loop.run_in_executor(None, fetch_tokens, slug)
            if pair is None:
                token_retry_after[slug] = now + TOKEN_RETRY_S
                continue
            markets[slug] = {"asset": asset, "start": start, "up": pair[0], "down": pair[1]}
            await sub_queue.put(("subscribe", {pair[0], pair[1]}))
            log_meta({"t": "BF_MARKET_READY", "slug": slug})
        expired = [s for s, m in markets.items() if m["start"] + WINDOW_S + 60 < now]
        for slug in expired:
            m = markets.pop(slug)
            strikes.pop(slug, None)
            books.pop(m["up"], None)
            books.pop(m["down"], None)
            await sub_queue.put(("unsubscribe", {m["up"], m["down"]}))
        for slug in [s for s, t in token_retry_after.items() if t + 900 < now]:
            token_retry_after.pop(slug, None)
        await asyncio.sleep(0.5)


def desired_tokens():
    out = set()
    for m in markets.values():
        out.add(m["up"])
        out.add(m["down"])
    return out


def apply_event(event, now):
    kind = event.get("event_type")
    if kind == "book":
        token = str(event.get("asset_id") or "")
        if not token:
            return
        book = books.setdefault(token, {"bids": {}, "asks": {}})
        book["asks"] = {}
        for lvl in event.get("asks") or []:
            try:
                px, sz = float(lvl.get("price")), float(lvl.get("size"))
            except (TypeError, ValueError, AttributeError):
                continue
            if sz > 0:
                book["asks"][px] = sz
        book["bids"] = {}
        for lvl in event.get("bids") or []:
            try:
                px, sz = float(lvl.get("price")), float(lvl.get("size"))
            except (TypeError, ValueError, AttributeError):
                continue
            if sz > 0:
                book["bids"][px] = sz
        book["init"] = True
        book["ts"] = now
    elif kind == "price_change":
        for change in event.get("price_changes") or []:
            token = str(change.get("asset_id") or "")
            if not token:
                continue
            book = books.setdefault(token, {"bids": {}, "asks": {}})
            try:
                px, size = float(change.get("price")), float(change.get("size"))
            except (TypeError, ValueError):
                continue
            side = str(change.get("side") or "").upper()
            ladder = book["asks"] if side == "SELL" else book["bids"] if side == "BUY" else None
            if ladder is None:
                continue
            if size > 0:
                ladder[px] = size
            else:
                ladder.pop(px, None)
            book["ts"] = now


def top(book):
    asks = book.get("asks") or {}
    bids = book.get("bids") or {}
    ask = min(asks) if asks else None
    bid = max(bids) if bids else None
    l2 = [[px, round(asks[px], 4)] for px in sorted(asks)[:L2_DEPTH]]
    depth = round(asks.get(ask, 0.0), 4) if ask is not None else None
    return bid, ask, depth, l2


def synth_row(asset, slug, m, now):
    up_book = books.get(m["up"])
    down_book = books.get(m["down"])
    if not up_book or not down_book or not up_book.get("init") or not down_book.get("init"):
        return None
    # Honest freshness: never re-stamp frozen books with a live ts_ms; if
    # neither side saw a WS event recently, suppress and let und rows rule.
    src_ts = min(float(up_book.get("ts") or 0.0), float(down_book.get("ts") or 0.0))
    if now - src_ts > BOOK_SRC_MAX_AGE_S:
        return None
    rem = m["start"] + WINDOW_S - now
    if rem < 0 or rem > WINDOW_S:
        return None
    up_bid, up_ask, up_depth, up_l2 = top(up_book)
    dn_bid, dn_ask, dn_depth, dn_l2 = top(down_book)
    if up_ask is None or dn_ask is None:
        return None
    mid_up = ((up_bid if up_bid is not None else up_ask) + up_ask) / 2.0
    fav_is_up = mid_up >= 0.5
    if fav_is_up:
        fav = (up_bid, up_ask, up_depth, up_l2, "YES")
        und = (dn_bid, dn_ask, dn_depth, dn_l2, "NO")
    else:
        fav = (dn_bid, dn_ask, dn_depth, dn_l2, "NO")
        und = (up_bid, up_ask, up_depth, up_l2, "YES")
    und_mid = ((und[0] if und[0] is not None else und[1]) + und[1]) / 2.0
    obs = chain_px.get(asset)
    return {
        "event": "snap", "tf": "5m", "asset": asset, "slug": slug,
        "cycle_start": m["start"], "cycle_end": m["start"] + WINDOW_S,
        "rem_sec": int(rem), "ts_ms": int(now * 1000), "src": "book_fast",
        "fav_side": fav[4], "fav_bid": fav[0], "fav_ask": fav[1],
        "fav_ask_depth": fav[2], "fav_ask_l2": fav[3],
        "und_side": und[4], "und_bid": und[0], "und_ask": und[1],
        "und_ask_depth": und[2], "und_ask_l2": und[3],
        "und_mid": round(und_mid, 4),
        "strike": resolve_strike(slug, m["start"], now),
        "spot": obs[1] if obs else None,
    }


async def emitter():
    global n_rows
    last_emit = {}
    last_top = {}
    last_rotate = 0.0
    while True:
        now = time.time()
        for slug, m in list(markets.items()):
            if not (m["start"] <= now < m["start"] + WINDOW_S):
                continue
            asset = m["asset"]
            row = synth_row(asset, slug, m, now)
            if row is None:
                continue
            key = (row["fav_bid"], row["fav_ask"], row["und_bid"], row["und_ask"])
            if key == last_top.get(asset) and now - last_emit.get(asset, 0.0) < EMIT_MAX_INTERVAL_S:
                continue
            last_top[asset] = key
            last_emit[asset] = now
            with open(OUT, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            n_rows += 1
        if now - last_rotate > 600:
            last_rotate = now
            rotate_if_needed()
            log_meta({"t": "BF_ALIVE", "rows": n_rows, "markets": len(markets),
                      "books": sum(1 for b in books.values() if b.get("init"))})
        # Coalesce L2 bursts at 5 Hz. The execution engine keeps its own
        # direct WS book, so this file feed only needs to remain comfortably
        # inside the detector's 3 s freshness window.
        await asyncio.sleep(0.2)


async def chainlink_tail():
    """Tail the basis feed for chainlink rows (strike + spot source)."""
    f = None
    ino = None
    while True:
        try:
            if f is None:
                f = open(BASIS, "r", errors="ignore")
                f.seek(0, 2)
                ino = os.fstat(f.fileno()).st_ino
            line = f.readline()
            if not line:
                try:
                    st = os.stat(BASIS)
                    if st.st_ino != ino or st.st_size < f.tell():
                        f.close()
                        f = None
                except Exception:
                    pass
                await asyncio.sleep(0.2)
                continue
            if '"src":"chainlink"' not in line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            sym = str(row.get("sym") or "").lower()
            asset = CL_SYMBOL.get(sym)
            if asset is None:
                continue
            try:
                px = float(row.get("px") or 0)
                ts = float(row.get("ts") or 0)
            except (TypeError, ValueError):
                continue
            if px > 0:
                chain_px[asset] = (ts, px)
                hist = chain_hist.get(asset)
                if hist is None:
                    hist = chain_hist[asset] = collections.deque(maxlen=40)
                hist.append((ts, px))
        except Exception:
            try:
                if f is not None:
                    f.close()
            except Exception:
                pass
            f = None
            await asyncio.sleep(1.0)


async def ws_loop():
    subscribed = set()
    while True:
        desired = desired_tokens()
        if not desired:
            await asyncio.sleep(0.2)
            continue
        try:
            async with websockets.connect(
                WS_URL, open_timeout=8, close_timeout=3,
                ping_interval=20, ping_timeout=10,
                max_size=4 * 1024 * 1024, compression=None,
            ) as ws:
                initial = sorted(desired)
                await ws.send(json.dumps({"assets_ids": initial, "type": "market"}))
                subscribed = set(initial)
                log_meta({"t": "BF_WS_CONNECTED", "tokens": len(subscribed)})
                last_ping = 0.0
                recv_task = asyncio.create_task(ws.recv())
                try:
                    while True:
                        while not sub_queue.empty():
                            operation, tokens = await sub_queue.get()
                            tokens = set(tokens)
                            if operation == "subscribe":
                                tokens -= subscribed
                            else:
                                tokens &= subscribed
                            if tokens:
                                await ws.send(json.dumps({
                                    "assets_ids": sorted(tokens), "operation": operation,
                                }))
                                if operation == "subscribe":
                                    subscribed |= tokens
                                else:
                                    subscribed -= tokens
                        now = time.time()
                        if now - last_ping >= 8.0:
                            await ws.send("PING")
                            last_ping = now
                        done, _ = await asyncio.wait((recv_task,), timeout=0.1)
                        if not done:
                            continue
                        raw = recv_task.result()
                        recv_task = asyncio.create_task(ws.recv())
                        try:
                            data = json.loads(raw)
                        except Exception:
                            continue
                        events = data if isinstance(data, list) else [data]
                        now = time.time()
                        for event in events:
                            if isinstance(event, dict):
                                apply_event(event, now)
                finally:
                    if not recv_task.done():
                        recv_task.cancel()
                    await asyncio.gather(recv_task, return_exceptions=True)
        except Exception as exc:
            log_meta({"t": "BF_WS_RECONNECT", "error": str(exc)[:160]})
            for book in books.values():
                book["init"] = False
            await asyncio.sleep(1.0)


async def main():
    global sub_queue
    sub_queue = asyncio.Queue()
    rotate_if_needed()
    log_meta({"t": "BF_START", "assets": list(ASSETS), "prefetch_lead_s": PREFETCH_LEAD_S})
    await asyncio.gather(market_manager(), ws_loop(), emitter(), chainlink_tail())


if __name__ == "__main__":
    asyncio.run(main())
