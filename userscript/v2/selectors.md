# Torn Poker v2 DOM Anchors (Phase 2)

These anchors are used by `torn_poker_extractor.user.js`. CSS-module hashes
(e.g. `front___zu4oW`) may change after Torn deploys; prefer `[class*="prefix___"]`.

| Field | Primary strategy | Fallback |
|---|---|---|
| Root | `#mainPokerBox`, `[class*="pokerTable"]` | `main`, `body` |
| Pot | Text anchor `\bPOT\b` + money | `[class*="pot"]`, `[class*="totalPot"]` |
| Hero cards | Face-up `[class*="hand___"]` outside community | `[data-player-cards]` |
| Board | `[class*="communityCards___"]` face-up cards | `[data-board-cards]` |
| Hero stack | Hero seat `[id^="player-"]` / `[class*="yourTurn"]` money text | Chip/balance spans in hero zone |
| Hero turn | `[class*="yourTurn___"]` visible | Enabled action buttons present |
| Action slots | Bottom 3 enabled `button`/`a` sorted by X | `[class*="controls"]` children |
| Post-hand | Text SHOW CARDS / SIT OUT / LEAVE | `[class*="postHand"]` |

Enable calibration logging: `localStorage.torn_hud_v2_debug = "1"` then reload.
