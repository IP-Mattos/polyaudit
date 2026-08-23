#!/usr/bin/env python3
"""Juez historico del vigia: en tweet_watch.jsonl (conteos xtracker cada
~10 min + books L3 de cada bracket), medir que pasa DESPUES de que el conteo
cruza un techo (bracket muere) o un piso de cola superior (bracket cerrado).

Pregunta pre-registrada del colector: ¿cuanto y por cuanto tiempo queda el
mercado rezagado tras un cruce irreversible? Si la respuesta es "nada y
segundos", la especie del vigia no paga y no se arma nada."""
import os
import json
import re
from collections import defaultdict

SRC = os.environ.get("TWEET_WATCH", "data/tweet_watch.jsonl")

RANGE_RE = re.compile(r"post ([\d,]+)\s*[-–]\s*([\d,]+) tweets", re.I)
MORE_RE = re.compile(r"post ([\d,]+) or more tweets", re.I)
LESS_RE = re.compile(r"post (?:less|fewer) than ([\d,]+) tweets", re.I)
WIN_RE = re.compile(r"from (\w+ \d{1,2}) to (\w+ \d{1,2})", re.I)
CNT_WIN_RE = re.compile(r"tweets (\w+ \d{1,2}) - (\w+ \d{1,2}),", re.I)


def wkey(a, b):
    return (a.lower().replace(" ", ""), b.lower().replace(" ", ""))


def main():
    mkts = {}                       # id -> {lo, hi, win}
    cnt = defaultdict(list)         # win -> [(ts,total)]
    books = defaultdict(list)       # id -> [(ts, bid_px, bid_sz, ask_px)]
    for ln in open(SRC, encoding="utf-8"):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        t = r.get("t")
        if t == "PX" and r["id"] not in mkts:
            q = r.get("q") or ""
            if "Elon" not in q:
                continue
            w = WIN_RE.search(q)
            if not w:
                continue
            lo = hi = None
            m = RANGE_RE.search(q)
            if m:
                lo, hi = int(m.group(1).replace(",", "")), \
                    int(m.group(2).replace(",", ""))
            else:
                m = MORE_RE.search(q)
                if m:
                    lo, hi = int(m.group(1).replace(",", "")), None
                else:
                    m = LESS_RE.search(q)
                    if m:
                        lo, hi = 0, int(m.group(1).replace(",", "")) - 1
            if lo is None:
                continue
            mkts[r["id"]] = {"lo": lo, "hi": hi,
                             "win": wkey(w.group(1), w.group(2)),
                             "q": q}
        elif t == "CNT" and "Elon" in (r.get("title") or ""):
            w = CNT_WIN_RE.search(r["title"])
            if w and r.get("total") is not None:
                cnt[wkey(w.group(1), w.group(2))].append(
                    (r["ts"], int(r["total"])))
        elif t == "BOOK":
            bids = r.get("bid") or []
            asks = r.get("ask") or []
            bp, bs = (bids[0][0], bids[0][1]) if bids else (0.0, 0.0)
            ap = asks[0][0] if asks else 1.0
            books[r["id"]].append((r["ts"], bp, bs, ap))

    for v in cnt.values():
        v.sort()
    for v in books.values():
        v.sort()
    print(f"mercados con bracket: {len(mkts)} | ventanas con conteo: "
          f"{len(cnt)} | mercados con book: {len(books)}")

    def book_at(bid, ts):
        arr = books.get(bid) or []
        for row in arr:
            if row[0] >= ts:
                return row
        return None

    deaths, locks = [], []
    for mid, mk in mkts.items():
        series = cnt.get(mk["win"])
        if not series or mid not in books:
            continue
        lo, hi = mk["lo"], mk["hi"]
        cross_ts, kind = None, None
        prev_ok = False
        for ts, total in series:
            if hi is not None:
                if total > hi and prev_ok:
                    cross_ts, kind = ts, "death"
                    break
                prev_ok = total <= hi
            else:
                if total >= lo and prev_ok:
                    cross_ts, kind = ts, "lock"
                    break
                prev_ok = total < lo
        if not cross_ts:
            continue
        b0 = book_at(mid, cross_ts)
        if not b0:
            continue
        traj = {}
        for lag_s, tag in ((0, "t0"), (600, "t10m"), (1800, "t30m"),
                           (3600, "t60m")):
            b = book_at(mid, cross_ts + lag_s)
            if b:
                traj[tag] = b
        rec = {"q": mk["q"][:70], "cross_ts": cross_ts, "traj": traj}
        (deaths if kind == "death" else locks).append(rec)

    print(f"\ncruces observados con book: muertes {len(deaths)}, "
          f"cierres {len(locks)}\n")

    def show(recs, kind):
        if not recs:
            print(f"{kind}: sin casos")
            return
        print(f"== {kind} ==")
        edged = 0
        for r in recs:
            t0 = r["traj"].get("t0")
            if kind == "MUERTES":
                # comprar NO ~ (1 - yes_bid); edge si yes_bid > 0.07
                e0 = t0[1] if t0 else 0
                has = e0 > 0.07
                path = " -> ".join(
                    f"{tag}:bid {r['traj'][tag][1]:.2f}x{r['traj'][tag][2]:.0f}"
                    for tag in ("t0", "t10m", "t30m", "t60m")
                    if tag in r["traj"])
            else:
                # comprar YES al ask; edge si ask < 0.93
                e0 = t0[3] if t0 else 1
                has = e0 < 0.93
                path = " -> ".join(
                    f"{tag}:ask {r['traj'][tag][3]:.2f}"
                    for tag in ("t0", "t10m", "t30m", "t60m")
                    if tag in r["traj"])
            edged += has
            print(f"  [{'EDGE' if has else '    '}] {r['q']}")
            print(f"         {path}")
        print(f"  -> con edge al primer book tras el cruce: "
              f"{edged}/{len(recs)}")

    show(deaths, "MUERTES")
    print()
    show(locks, "CIERRES")


if __name__ == "__main__":
    main()
