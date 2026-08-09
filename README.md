# polyaudit

### Can I copy this trader? — the one question the leaderboards do not answer.

A wallet can show six figures of public "profit", lose money on every trade,
and stay alive on a volume rebate you will never qualify for. Fee trackers
show the toll; reward pages show the refund; nobody nets them into a single
number and says which side of the line the wallet is on.

This does. One command, no account.

```
$ python audit.py 0xf418d3a1a941292f9c8707d62a14980c5beb95a3

  activo 2026-05-07 -> 2026-08-03 | 208,360 trades en 11,425 mercados

  PNL REAL (fee y rebates incluidos): $23,499.59
  el perfil publico dice:             $101,914.56   <-- pre-fee

  fee pagado $106,216.37 | rebates $27,782.08 | maker 0.4% de los fills
  top-5 mercados = 1.1% de las ganancias | mitades -7,018 / +2,632

  LECTURA:
   - SU TRADING PIERDE - la ganancia sale del rebate por volumen.
     Copiar sus trades sin ese tier es perder.
   - El perfil publico exagera en $78,415 (no descuenta el fee).
```

That wallet advertises its bot for sale at $8,000.

That report is the 2026-05-07 → 08-03 window, measured with a $19 reconciliation
residual. A re-run six days later (`examples/takerner_2026-08-09.json`) put the
without-rebate result at ≈+$4.2k — a sign flip that sits inside that run's own
$2.6k residual. An audit is a dated photograph, not a permanent truth: the
stable finding across both windows is a trading result of roughly zero with the
rebate at ~88% of net income.

## What the leaderboard does not tell you

| field | what it looks like | what it is |
|---|---|---|
| `pnl` | profit in dollars | profit **before the trading fee**, and before rebates |
| `vol` | volume in dollars | volume in **shares** |

The fee is never a separate line. It is embedded inside `usdcSize`: a buy of 30
shares at 0.63 debits 19.39, not 18.90. The gap is the fee, and on a wallet
doing hundreds of thousands of fills it dwarfs the trading result.

## What this measures

- **Real PnL** — every cash flow that moved: buys, sells, redemptions, merges
  and splits, plus `MAKER_REBATE` / `TAKER_REBATE`, plus the open book.
- **Fee actually paid** — per fill, as `usdcSize - price*shares`.
- **Maker vs taker split** — inferred from the fee on each fill. A wallet at
  90%+ maker is running a quoting business, not picking winners; its trades are
  not copyable as signals.
- **Anti-luck shape** — how much of the profit sits in five markets, whether
  both halves of the history are positive, how many days carried the rest. A
  wallet whose entire lifetime profit came from one volatile afternoon is a
  survivor, not a strategy.
- **Whether it lives on the rebate** — trading result with the subsidy removed.
  This is the difference between a business you can copy and one you cannot.

## The reconciliation guard

A number that cannot be checked should not be published. Every audit is tested
against an identity that uses an independent figure:

```
official_pnl  ≈  real_pnl + fees − rebates
```

because the venue's number is blind to both. When the gap exceeds 5%, the tool
says **NO CONFIABLE** and explains why, instead of printing a tidy wrong answer:

```
  LECTURA:
   - NO CONFIABLE: las cuentas no cierran contra el dato publico (desvio 922.0%).
     Faltan eventos: 41410 cobros vienen en cero en la API.
     No publicar estos numeros.
```

That wallet has 53,000 profile views and is cited in viral threads as a
million-dollar success. Its redemption events come back empty from the public
API, so its real result cannot be reconstructed from activity alone — and
saying so is the correct output.

One thing the identity cannot check, by construction: the rebate line. Because
`real_pnl` already contains rebates, they cancel out of `real + fees − rebates`;
the guard tests the reconstruction of cash flows, open value and fees against
the venue's figure — not the rebate amount. Rebates are not inferred, though:
they are read from explicitly labeled events (`TAKER_REBATE`, `MAKER_REBATE`),
and for the exhibit wallet they match an independent on-chain reconstruction
from Polygon transfer events to within 0.1%.

## Usage

```bash
python audit.py 0xADDRESS          # human-readable report
python audit.py 0xADDRESS --json   # machine-readable
```

Only the standard library. No key, no account. Requests are spaced 350ms and
retried on failure — a timeout must never be mistaken for the end of a history.

### Reproducing an audit

The cutoff of an audit is the moment you run it: history is walked backwards
from now until exhausted, so re-running the same command later covers a longer
period — compare periods, not totals. `examples/` holds dated `--json` outputs
committed as-is, each reproducible with the single command above. A large
wallet (200k+ events) takes several minutes at the built-in request spacing.

## Limits, stated plainly

- Large wallets (hundreds of thousands of events) take several minutes.
- The maker/taker split is inferred from the per-fill fee. Polymarket rounds
  fees to five decimals, so a dust-sized taker fill near an extreme price can
  round to a zero fee and be counted as maker. This can nudge the maker
  percentage slightly; the dollar totals are unaffected, because they are built
  from actual cash flows, not from the classification.
- Some wallets return zero-valued redemptions from the public API. Their real
  result needs on-chain reconstruction; this tool detects the case and refuses
  to report rather than guessing.
- History is walked backwards until exhausted; if the ceiling is reached the
  report says the period is partial.
- Passing the 5% guard bounds the books; it does not settle every derived
  number. When a quantity of interest — say, a without-rebate result of a few
  thousand dollars — is the same order as the run's reconciliation residual,
  its sign is not resolved, and the report should be read that way.
- Per-day, half-history and per-market shapes are cash-flow based: a position
  bought today and redeemed in two weeks debits one day and credits another.
  They describe the shape of the money, not time-weighted returns.
- REAL PNL includes the open book at the API's current valuation — for wallets
  with large open positions it is marked-to-market, not realized cash.
- Everything labeled `REBATE` plus plain `REWARD` is counted as subsidy income
  in a single bucket. The API distinguishes more types (`TAKER_REBATE`,
  `MAKER_REBATE`, `REWARD`, `REFERRAL_REWARD`…); the bucket answers "does the
  trading pay without subsidies", not "which subsidy".
- This measures what happened. It does not predict, and it is not advice.

## What is already covered elsewhere, and what is not

That the public figure ignores fees is known: several trackers already subtract
them. What none of them do is net the **rebate** back in. PolyScalping says so
in its own disclaimer — it publishes gross fees and leaves the offsetting
rewards on a separate page, to be cross-referenced by hand. The consequence is
that a wallet paying $500k in fees while collecting $600k in rebates looks
identical to one that is simply bleeding.

That single number is the difference between a business you can copy and one
you cannot, because the rebate scales with volume you will never have. This
tool reports it, states when the trading result is negative without the
subsidy, and refuses to answer when the underlying data cannot support one.

Of nine wallets audited this way — several of them cited in threads with
hundreds of thousands of views — four were losing money on their trades and
surviving on rebates. One of them sells its bot for $8,000.

## License

MIT
