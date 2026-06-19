# Torn HUD v2 — Data Sources

v2 is a **pure in-browser decision engine**. It does not scrape Torn poker DOM for
cards or equity. Install **Torn Poker Helper** (GreasyFork 538541) alongside this script.

## Poker Helper reads (overlay panel)

Reads from Torn Poker Helper's `#mainPokerBox` panel — data attributes first,
row-label fallback second.

| Field | Data attribute | Row label (EN) |
|---|---|---|
| Hero cards | `[data-player-cards]` | Your cards |
| Board | `[data-board-cards]` | Board |
| Hand name | `[data-combination]` | Combination |
| Win probability | `[data-win-probability]` | Win chance |
| Active players | `[data-active-players]` | Active players |

Active player count drives preflop range thresholds (7-way much tighter than heads-up).

## Torn DOM reads (Helper does NOT expose these)

| Field | Strategy |
|---|---|
| Pot | `POT:` text node in game area (excludes Helper panel) → sibling value |
| Call amount | Call button label (e.g. `Call $120`); CHECK / Call Any → 0 |
| Hero stack | `[class*="playerMeGateway"]` money element |
| Action buttons | Bottom bar near `[class*="yourTurn___"]` / `[class*="controls"]` |

## Edge cases

- **Pot unavailable** (pre-deal): overlay shows `Pot —`, EV disabled; preflop range logic still runs from win % + player count.
- **CHECK available** (call = 0 or missing): shows `CHECK available`, skips fold/call EV comparison.

## Computed metrics

- **Pot odds** = `call / (pot + call)` — only when pot and call amount both known
- **SPR** = `stack / pot`
- **EV** = `(win_prob × pot) − ((1 − win_prob) × call)` — disabled when pot unavailable or CHECK available

## Overlay

Bottom-right panel (`#torn-hud-v2-decision-overlay`, z-index 99998) shows:
`Pot Odds | SPR | EV | Decision` plus one-line reasoning.

Does not modify or overlap Torn Poker Helper's HUD (z-index 99999).
