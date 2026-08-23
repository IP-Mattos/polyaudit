#!/usr/bin/env python3
"""Low-latency Binance trade feed for the K4LAG detector.

Writes data/binance_fast.jsonl with the same row schema as the Node
basis collector ({"src":"binance","sym","px","ts_ms","ts"}) plus "feed":"fast",
sourced from the Binance aggTrade WebSocket push instead of the ~1 Hz snapshot.

Write policy per symbol:
  * always write the FIRST trade of each new second (the detector samples one
    price per second; this row is what moves detection ~0.4s earlier);
  * otherwise write only when the price changed and >=100 ms passed.

This process is read-only market data: no keys, no orders.
"""
import asyncio
import json
import os
import time

import websockets

OUT = os.environ.get("BINANCE_FAST_OUT", "data/binance_fast.jsonl")
URL = "wss://stream.binance.com:9443/stream?streams=btcusdt@aggTrade/ethusdt@aggTrade"
MIN_INTERVAL_S = 0.10
ROTATE_BYTES = 250 * 1024 * 1024
ROTATE_KEEP_S = 48 * 3600


def rotate_if_needed():
    try:
        if os.path.getsize(OUT) >= ROTATE_BYTES:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            os.replace(OUT, OUT + "." + stamp)
        base = os.path.basename(OUT) + "."
        folder = os.path.dirname(OUT)
        for name in os.listdir(folder):
            suffix = name[len(base):]
            # Only touch our own timestamped rotations (e.g. .20260720T190000Z),
            # never an operator's .bak or similar.
            if name.startswith(base) and suffix.startswith("20") and suffix.endswith("Z"):
                path = os.path.join(folder, name)
                if time.time() - os.path.getmtime(path) > ROTATE_KEEP_S:
                    os.remove(path)
    except FileNotFoundError:
        pass
    except Exception:
        pass


async def run_stream():
    last_px = {}
    last_write = {}
    last_sec = {}
    n_rows = 0
    async with websockets.connect(
        URL, open_timeout=8, close_timeout=3, max_size=1 * 1024 * 1024, compression=None
    ) as ws:
        print(json.dumps({"t": "FAST_FEED_CONNECTED", "ts": round(time.time(), 3)}), flush=True)
        last_rotate_check = 0.0
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            try:
                msg = json.loads(raw)
                data = msg.get("data") or {}
                sym = str(data.get("s") or "").lower()
                px = float(data.get("p") or 0)
                trade_ms = int(data.get("T") or 0)
            except (TypeError, ValueError):
                continue
            if not sym or px <= 0 or trade_ms <= 0:
                continue
            now = time.time()
            sec = trade_ms // 1000
            new_second = sec != last_sec.get(sym)
            changed = px != last_px.get(sym)
            throttled = now - last_write.get(sym, 0.0) < MIN_INTERVAL_S
            if not new_second and (not changed or throttled):
                continue
            last_sec[sym] = sec
            last_px[sym] = px
            last_write[sym] = now
            row = {"src": "binance", "sym": sym, "px": px,
                   "ts_ms": trade_ms, "ts": round(now, 3), "feed": "fast"}
            with open(OUT, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            n_rows += 1
            if now - last_rotate_check > 600:
                last_rotate_check = now
                rotate_if_needed()
                print(json.dumps({"t": "FAST_FEED_ALIVE", "rows": n_rows,
                                  "ts": round(now, 3)}), flush=True)


async def main():
    rotate_if_needed()
    backoff = 1.0
    while True:
        started = time.time()
        try:
            await run_stream()
        except Exception as exc:
            if time.time() - started > 60:
                backoff = 1.0
            print(json.dumps({"t": "FAST_FEED_RECONNECT", "error": str(exc)[:160],
                              "backoff_s": backoff,
                              "ts": round(time.time(), 3)}), flush=True)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 60.0)


if __name__ == "__main__":
    asyncio.run(main())
