# Sampling frame — every wallet this project attempted to audit

Population: **wallets publicly promoted as profitable** — leaderboard-cited,
quoted in threads with significant reach, or attached to a bot or signal
service for sale. Deliberately not a random sample of the venue: it is the
population a "can I copy this trader" question is actually about.

Inclusion path for every entry: the wallet was named as successful by a
public source (leaderboard, viral thread, bot advertisement) before the
audit ran; the address came from that source or from resolving its profile,
never from screening outcomes first.

Statuses: **reconciled** = identity gap ≤ 5%; **censored** = audit ran and
the guard refused (NO CONFIABLE); **incomplete** = attempted, no final
verdict delivered (analyst attention, not the guard).

## July 2026 pass (run 2026-07-29 → 2026-08-04; per-wallet gap figures live
in the session records; summary preserved in the project log)

| # | Wallet | Promoted as | Status |
|---|--------|-------------|--------|
| 1 | takerner (0xf418...) | +$99-101k profile, sells bot $8,000 | reconciled |
| 2 | doggystyie (0x0484...) | +$214.8k profile | reconciled |
| 3 | Agile-Spacing (0xce25...) | +$533k lifetime | reconciled |
| 4 | Impressive-Steak (0x06dc...) | +$495k profile | reconciled |
| 5 | mo-money (0x32ed...) | +$198k profile | reconciled |
| 6 | ssdfj156ssz (0xcd46...) | tape top-earner | reconciled |
| 7 | 0x0a10 / w1 (0xd4fa2e10...) | tape top-earner, 2.29M events | reconciled (≤1%) |
| 8 | elrey (0x5ed5a529...) | tape top-earner +$37k | reconciled |
| 9 | trumbit | tape top-earner | reconciled |
| 10 | alpha5ii-copybestbot | "copy best bot" branding | reconciled (≤1%) |
| 11 | 0xb7e6... | tape signal candidate | reconciled (≤1%) |
| 12 | hypnoyoda (0x7dcd...) | tape top-earner | reconciled |
| 13 | 0xee65685d | viral "$1000→$980k" thread with referral codes | **censored** — 41,410 zero-valued redemptions |
| 14 | bobbybrant (0x9028...) | in-play soccer winner | incomplete |
| 15 | aibird | tape candidate | incomplete |
| 16 | nihiiism (0x5c46...) | 13-month track | incomplete (1.3GB history fetched, report never delivered) |

## August 2026 pass (run 2026-08-10/11; full JSON outputs in this repo's
history and the project scratchpad)

| # | Wallet | Promoted as | Events walked | Gap | Status |
|---|--------|-------------|---------------|-----|--------|
| 17 | takerner re-run | (same wallet, fresh window) | 234,911 | 2.2% | reconciled |
| 18 | 0x13f0bcec | X thread "sweeper bot $35K PNL", referral link | 106,709 | 394.8% (359 zero redeems) | **censored** |
| 19 | 0xf705fa04 | leaderboard +$1.89M | 48,787 | 40.9% (921 zero redeems) | **censored** |
| 20 | bonereaper (0xeebd...) | leaderboard +$1.24M | 600,351 (cap hit, last 18 days only) | 95.6% | **censored** (truncation + zero redeems) |

Six additional leaderboard wallets received a bounded triage
(~2,000-event fingerprint, no reconciliation attempt) on 2026-08-11 and are
not part of the audited sample: llamaloco0000, d7422d98, noman2026, btc333
and two unresolved handles.

## Is the censoring random? Checked, with a counterexample

The failure mode is zero-valued redemptions, so the naive story is
"bigger wallets get censored". The record does not support size alone:
the **largest wallet ever reconciled had 2.29M events** (0x0a10 — maker
pairs merged, near-zero redemption dependence), while a censored wallet
had only 48,787. What the censored set shares is **style, not size**:
all four are redemption-heavy flows (sweep/redeem or taker-redeem loops)
— precisely the styles where volume subsidies (rebates) matter most.

Direction of the bias, stated carefully: the guard disproportionately
censors the styles most likely to be subsidy-dependent. If those wallets
could be reconciled, the "trading loses without the rebate" count would
more plausibly rise than fall. The published 4-of-9 figure from the early
rebate pass should therefore be read as closer to a floor than a ceiling —
but this is an inference about censoring direction, not a measurement.

## Pre-registration note

From 2026-08-11 onward, inclusion criteria for any new audit batch are
committed to this repository before the batch runs; the commit hash is the
timestamp. Earlier passes were selected by the criteria above but not
pre-committed — that is a limitation of the early record, stated rather
than papered over.
