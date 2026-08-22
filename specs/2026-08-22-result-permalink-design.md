# Result permalink — design

**Date:** 2026-08-22
**Status:** proposed

## Problem

The browser auditor produces the one number people want to share — the gap
between the public profile figure and the real, fee- and rebate-netted PnL.
That result currently lives only in the tab that produced it. There is no URL
to send, so every audit dies where it was run.

`docs/audit.js` reads the address from a form field only. It never reads or
writes `location.search`, and it exposes no way to reproduce a run by link.

## Goal

Make every audit addressable by URL, so a result can be sent, linked and
reproduced by the person who receives it.

## Non-goals

- No server, no stored results, no analytics. The site stays static.
- No embedding of computed figures in the URL (see Decisions).
- No index or ranking of wallets. That is a separate, later piece of work.

## Behaviour

**Reading.** On load, `auditor.html` reads `?w=<address>` and the optional
`&cap=<n>` from the query string.

- `w` valid against `/^0x[0-9a-fA-F]{40}$/` — prefill the field, select the
  matching cap, and start the audit automatically.
- `w` present but malformed — prefill the field, show the existing address
  error, and start nothing. No requests are issued for a bad address.
- `cap` absent or not one of the values the select offers — fall back to the
  select's current default. Never widen a shared run beyond what the link asks.
- `w` absent — current behaviour, unchanged.

**Writing.** On a completed audit (including a cancelled partial run that still
rendered a report), replace the URL via `history.replaceState` with
`?w=<lowercased address>&cap=<cap>`. No new history entry, so the back button
keeps its current meaning.

**Copying.** A "Copy link" button sits next to the existing download button,
enabled under the same condition (`lastResult` is set). It copies the current
absolute URL and confirms in place. Where `navigator.clipboard` is unavailable
or rejects, it selects the URL in a readonly input as a fallback.

## Decisions

**The link re-runs the audit; it does not carry the numbers.**

Encoding results in the URL would make an audit forgeable: anyone could hand
out a link that renders invented figures under this project's name. That
directly contradicts the reconciliation guard, whose whole purpose is to refuse
to publish a number that does not tie out. A link that recomputes from public
data is the only form that stays honest.

The cost is that a shared link can produce a different figure than the sender
saw, because the wallet keeps trading. That is already the project's stated
position — an audit is a dated photograph, not a permanent truth — so the
report must carry the run date visibly for the reader to place it.

**`cap` travels with the address.** Two runs at different caps cover different
slices of history and yield different figures. A link that omits the cap is not
reproducible, which is the property the link exists to provide.

## Affected files

- `docs/audit.js` — query-string read on load, `replaceState` after a run,
  copy-link handler. Additive; no existing function changes shape.
- `docs/auditor.html` — copy-link button and its fallback input, in the
  existing report actions row.
- `docs/styles.css` — only if the fallback input needs a rule.

## Verification

Manual, against the live page:

1. `?w=0xf418d3a1a941292f9c8707d62a14980c5beb95a3` runs on load and renders.
2. A hand-typed run rewrites the URL; pasting that URL in a clean tab
   reproduces the same report shape for the same cap.
3. `?w=0xzzz` shows the address error and issues no network requests.
4. `?w=<valid>&cap=999999` falls back to the default cap rather than widening.
5. No `?w=` behaves exactly as today.
