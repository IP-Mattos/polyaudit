# Sampling frame — every wallet this project attempted to audit

**Count note (19 → 9/8 → 4):** the early rebate-focused pass is recorded
as **8 wallets** in the session log while an earlier version of the
README said "nine". The discrepancy is an early-era record-keeping gap,
flagged here rather than resolved by picking the convenient number. The
headline figure is therefore stated as "4 of the early pass (8 per the
session log)".

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

## Is the censoring random? Measured — and the measurement corrected us

An earlier revision of this file inferred that the censoring points
against the headline finding, making "4 of 9" a floor. **Measuring it
refuted that inference.** The correction is preserved here and in the
git history rather than silently harmonized.

**Size does not censor**: the largest wallet ever reconciled had 2.29M
events (0x0a10), while a censored wallet had 48,787.

**Style alone does not censor either**: takerner is redemption-heavy
($4.26M redeemed vs $20k sold) and reconciled at a 2.2% gap. What
censors is the **magnitude of zero-valued redemptions** — 213 (passed)
vs 921 vs 41,410 (refused).

**Subsidy-dependence is measurable without reconciliation** (maker share
from the per-fill fee; rebates from explicitly labeled events), so we
measured it in the censored set: the sweeper (98.9% maker) earns its
income from spread, rebates $2,468 — not subsidy-dependent; 0xf705
(rebates $18,430 vs $98,511 fees) — not subsidy-dependent; bonereaper
(trading ≈ −$4,778 in-window, rebates $47,713) — subsidy-dependent;
0xee65 — unmeasured. That is **1 of 3 measurable censored wallets**
against roughly **4 of 8 in the early reconciled pass**.

Conclusion, stated at the strength the data supports: **the censoring
shows no clear direction with respect to the rebate-dependence finding.**
The 4-of-early-pass figure is neither a floor nor a ceiling; it is the
measured rate among wallets whose books close, full stop.

## Pre-registration note

From 2026-08-11 onward, inclusion criteria for any new audit batch are
committed to this repository before the batch runs; the commit hash is the
timestamp. Earlier passes were selected by the criteria above but not
pre-committed — that is a limitation of the early record, stated rather
than papered over.
