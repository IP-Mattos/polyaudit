# research — the code behind the graveyard

A list of dead strategies is worth nothing without the instrument that killed
them. These are the actual measurement scripts, one per claim, each printing
the numbers quoted on the site. Run any of them and argue with the output, not
with us.

They come in two kinds. The first answers its question from public endpoints
alone and runs today on a bare machine. The second is an instrument from the
live desk that reads a tape we captured ourselves, which this repository does
not ship. Both are here, because a verdict you cannot inspect is only an
assertion.

## Self-contained: run them today

Standard library plus public APIs. No keys, no account, no data files to
download.

Every script states its rule **in its own docstring, before the results**, and
each one charges the fee, reports both halves of the sample, and was written
before its result was known. That ordering is the whole discipline: a rule
invented after seeing the data measures nothing but the data.

| script | the claim it tests | what came back |
|---|---|---|
| `binance_sweep.py` | Momentum / reversion / breakout rules on BTC and ETH across 15m, 1h, 4h and 1d, thresholds fixed in advance | 24 of 24 cells negative. On 15m and 1h the loss per trade is **−0.20 to −0.24%**, which is the round-trip fee — gross ≈ 0, so there is no timing signal to capture, only a toll to pay |
| `pump_study.py` | "Detect a pump and ride it": 100 small USDT pairs, 90 days, enter at the close of the +10% hourly candle — the first bar a detector can honestly act on | ~13 pumps/week exist, so the phenomenon is real. From the honest entry: **−1.79% median at +1h, −6.85% at +24h**, win rate 33-40%. The 24h run-up before the trigger is **+21.7%** — to be "early" you must predict that |
| `newcoin_dream.py` | New listings: the dream (sell the exact top of the first month) against the reality (close of day 30) | Dream **+12.2% median, peaking on day 4**. Reality **−21.4% median**, 19% end positive. Survivors only — delisted coins are not in the sample, so the real distribution is worse |
| `grid_trap.py` | "Buy, take +X%, repeat" with no stop, marked to market at the end | The trap in one line: closed clips **100% winners**, account **−45%**. The bag is not a footnote, it is the position |
| `sl_tactics.py` | Does a stop-loss fix the above? Four pre-registered TP/SL pairs | All worse than no stop, monotonically in trade count. The busiest variant paid **171% of capital in fees** in one year and finished at −90%. Exit tactics manage an edge; they cannot create one |
| `mm080_study.py` | Resting a maker bid at 0.80 on the leading side of a 5-minute market — does the fill hold often enough to pay? | Fill holds **74.1%** (95% CI 69.0-78.7) against a **77% breakeven**: −2.1c per share. The closest any cell came to the line. The proxy is *generous* — it assumes your bid is first in the queue |
| `triage.py` | Fingerprint any wallet in seconds: maker share, buy-price band, clip size, market family, buys vs redemptions | Used on leaderboard names to separate quoting businesses from directional bettors before spending minutes on a full audit |

`mm080_result.txt` is the raw output of the 0.80 run, kept as it printed.

## Capture first, then measure

These read a tape this repository does not ship, because the tape is gigabytes
of our own capture. Read the logic and find the bug in it, or run the collector
for a few days and produce your own tape. Every path is an environment variable
with a relative default, so nothing points at our machine.

| script | role | the claim it serves | needs |
|---|---|---|---|
| `binance_fast_feed.py` | collector | — | Binance aggTrade WebSocket. Writes `data/binance_fast.jsonl` |
| `book_fast_feed.py` | collector | — | Polymarket CLOB market WebSocket, live L2 books for the current and next 5m btc/eth up-down markets. Writes `data/book_fast.jsonl` |
| `k4lag_study.py` | study | **Latency arbitrage is dead.** 3,236 arm-settles across four posting delays (350/500/700/1000ms), non-fills booked at zero. The decay curve of a latency edge, measured on our own tape | a `k4lag_live.jsonl` shadow log |
| `lag_judge.py` | study | **Tweet-pace models lose to the market.** What actually happens after a bracket count crosses its ceiling or its lower floor | a `tweet_watch.jsonl` capture |

Both feeds are read-only market data. Neither reads a key, neither holds a
wallet, and neither can place an order. Check that yourself rather than taking
it from us; it is four files.

`k4lag_study.py` is worth reading even if you never run it, for one line in its
docstring: it reports **per opportunity, not per fill**. A signal that never
filled is booked at zero rather than dropped. Drop them instead and the same
tape shows an edge that is not there. That is the whole difference between the
two answers.

## The instrument worth stealing

`mm080_study.py` contains something more reusable than its verdict: **the 5-minute
markets are addressable retroactively.** Their slugs are deterministic —
`btc-updown-5m-{unix_timestamp}` on the 5-minute boundary (and
`btc-updown-15m-{ts}` for the 15-minute book) — so
`gamma-api.polymarket.com/events?slug=...` returns closed candles long after
they resolve, complete with `conditionId`. From there the public trade tape
(`data-api.polymarket.com/trades?market={conditionId}`) and the settlement
truth (`clob.polymarket.com/markets/{conditionId}` → `tokens[].winner`) are
both reachable.

That means a 5-minute hypothesis can be measured against hundreds of already
closed candles today, instead of waiting a week for a live capture. The study
above went from question to verdict in about two hours, for nothing.

## Two rules these scripts exist to enforce

**Price entries at an executable quote, never at a print.** A cell of ours once
passed a pre-registered gate at t=3.44 on printed prices; re-priced at the
executable ask from a book recorder, the same entries gave t=0.27. Prints
underreact because they are old, not because the market is slow.

**Check what the timestamp means before believing the finding.** A pre-open
effect of +15.7c at t=16.9 across 236 wallets evaporated when a
discontinuity test showed no jump at the exogenous candle boundary: the
public API's `timestamp` is order *placement* time, not execution time.

## Running them

```bash
python research/binance_sweep.py     # ~2 min
python research/pump_study.py        # ~15 min (100 pairs)
python research/newcoin_dream.py     # ~10 min
python research/grid_trap.py         # ~1 min
python research/sl_tactics.py        # ~1 min
python research/mm080_study.py       # ~2 h (576 candles, spaced requests)
python research/triage.py '{"label": "0xADDRESS"}'
```

Requests are spaced deliberately. These read public endpoints; please do not
remove the sleeps.

Numbers were produced on 2026-08-10/11 and move with the market. The method is
the durable part; re-run before quoting any figure.
