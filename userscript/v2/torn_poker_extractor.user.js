// ==UserScript==
// @name         Torn HUD v2 Decision Engine
// @namespace    torn-hud-v2
// @version      1.1.0
// @description  Pot odds / SPR / EV overlay — reads Torn Poker Helper HUD + Torn action bar
// @match        https://www.torn.com/poker*
// @match        https://www.torn.com/page.php?sid=poker*
// @match        https://www.torn.com/page.php?sid=holdem*
// @grant        none
// @run-at       document-idle
// ==/UserScript==
//
// Requires: Torn Poker Helper (GreasyFork 538541) installed and running on the table.
// No WebSocket, no external connections — runs entirely in the userscript sandbox.

(function tornHudV2DecisionEngine() {
  "use strict";

  const OVERLAY_ID = "torn-hud-v2-decision-overlay";
  const POLL_MS = 500;

  const HELPER_ROW_LABELS = {
    heroCards: [/your cards/i, /vos cartes/i, /deine karten/i, /tus cartas/i],
    board: [/^board$/i, /^plateau$/i, /^tablero$/i],
    combination: [/combination/i, /combinaison/i, /kombination/i],
    winProb: [/win chance/i, /win probability/i, /chance de gagner/i, /gewinnchance/i],
    activePlayers: [/active players/i, /joueurs actifs/i, /aktive spieler/i],
  };

  let pollTimer = null;
  let observer = null;
  let lastFingerprint = "";

  function textOf(node) {
    return (node?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function parseMoney(raw) {
    if (!raw) return null;
    const cleaned = String(raw).replace(/,/g, "");
    const match = cleaned.match(/\$?\s*(\d+(?:\.\d+)?)\s*([kKmM])?/);
    if (!match) return null;
    let value = Number.parseFloat(match[1]);
    const suffix = match[2]?.toUpperCase();
    if (suffix === "K") value *= 1000;
    if (suffix === "M") value *= 1000000;
    return Number.isFinite(value) ? Math.round(value) : null;
  }

  function parsePercent(raw) {
    if (!raw) return null;
    const text = String(raw).trim();
    if (/fold|folded|couch|retir|gefalt|pass|conseil/i.test(text) && !/%/.test(text)) return null;
    const match = text.match(/(\d+(?:\.\d+)?)\s*%/);
    if (!match) return null;
    const value = Number.parseFloat(match[1]) / 100;
    return Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : null;
  }

  function parseActivePlayers(raw) {
    if (!raw) return null;
    const match = String(raw).match(/(\d+)/);
    if (!match) return null;
    const n = Number.parseInt(match[1], 10);
    return Number.isFinite(n) && n >= 2 ? n : null;
  }

  function isBoardEmpty(raw) {
    if (!raw) return true;
    const lower = raw.toLowerCase();
    return (
      lower.includes("empty") ||
      lower.includes("vide") ||
      lower.includes("leer") ||
      lower.includes("vacío") ||
      lower.includes("waiting") ||
      lower.includes("attente") ||
      /🟢/.test(raw)
    );
  }

  function isInsideHelperPanel(node) {
    if (!node) return false;
    return Boolean(
      node.closest("#mainPokerBox") ||
        node.closest("[data-player-cards]") ||
        node.closest(`#${OVERLAY_ID}`)
    );
  }

  function getHelperPanel() {
    return document.getElementById("mainPokerBox") || document.querySelector("[data-player-cards]")?.closest("div");
  }

  function readHelperField(selector) {
    const panel = getHelperPanel();
    const el = panel ? panel.querySelector(selector) : document.querySelector(selector);
    return el ? textOf(el) : "";
  }

  function readHelperRowByLabel(labelPatterns) {
    const panel = getHelperPanel();
    if (!panel) return "";

    for (const el of panel.querySelectorAll("span, div, label")) {
      const label = textOf(el);
      if (!label || label.length > 48) continue;
      if (!labelPatterns.some((p) => p.test(label))) continue;

      const card =
        el.closest("[style*='margin-bottom']") ||
        el.closest("[style*='padding']") ||
        el.parentElement?.parentElement;
      if (!card) continue;

      const dataEl = card.querySelector(
        "[data-player-cards], [data-board-cards], [data-combination], [data-win-probability], [data-active-players], [data-advice]"
      );
      if (dataEl && dataEl !== el) return textOf(dataEl);

      const valueCandidates = Array.from(card.querySelectorAll("div, span"))
        .map((n) => textOf(n))
        .filter((t) => t && t !== label && !labelPatterns.some((p) => p.test(t)));
      if (valueCandidates.length) {
        return valueCandidates.sort((a, b) => b.length - a.length)[0];
      }
    }
    return "";
  }

  function readPokerHelperState() {
    const heroCards =
      readHelperField("[data-player-cards]") || readHelperRowByLabel(HELPER_ROW_LABELS.heroCards);
    const boardCards =
      readHelperField("[data-board-cards]") || readHelperRowByLabel(HELPER_ROW_LABELS.board);
    const handName =
      readHelperField("[data-combination]") || readHelperRowByLabel(HELPER_ROW_LABELS.combination);
    const winProbRaw =
      readHelperField("[data-win-probability]") || readHelperRowByLabel(HELPER_ROW_LABELS.winProb);
    const activePlayersRaw =
      readHelperField("[data-active-players]") || readHelperRowByLabel(HELPER_ROW_LABELS.activePlayers);

    return {
      heroCards,
      boardCards,
      handName,
      winProbRaw,
      activePlayers: parseActivePlayers(activePlayersRaw),
      activePlayersRaw,
      isPreflop: isBoardEmpty(boardCards),
      helperPresent: Boolean(getHelperPanel() && document.querySelector("[data-player-cards]")),
    };
  }

  // --- Torn game DOM (pot / stack / actions only) ---

  function getGameRoot() {
    for (const selector of ['[class*="pokerTable"]', '[class*="tableWrapper"]', "#root", "main"]) {
      const node = document.querySelector(selector);
      if (node && !node.querySelector("[data-player-cards]")) return node;
    }
    return document.body;
  }

  function readPot() {
    const gameRoot = getGameRoot();

    const walker = document.createTreeWalker(gameRoot, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode;
      const raw = node.textContent || "";
      if (!/POT\s*:/i.test(raw)) continue;
      if (isInsideHelperPanel(node.parentElement)) continue;

      const labelEl = node.parentElement;
      if (!labelEl) continue;

      const container = labelEl.parentElement;
      if (container) {
        for (const child of container.children) {
          if (child === labelEl) continue;
          const text = textOf(child);
          if (!/\$/.test(text)) continue;
          const parsed = parseMoney(text);
          if (parsed !== null) return { raw: text, parsed, source: "pot-colon-sibling" };
        }
      }

      const combined = textOf(labelEl.parentElement || labelEl);
      const parsed = parseMoney(combined.replace(/POT\s*:/i, ""));
      if (parsed !== null && (combined.match(/\$/g) || []).length === 1) {
        return { raw: combined, parsed, source: "pot-colon-inline" };
      }

      const next = labelEl.nextElementSibling;
      if (next) {
        const text = textOf(next);
        const nextParsed = parseMoney(text);
        if (nextParsed !== null) return { raw: text, parsed: nextParsed, source: "pot-colon-next" };
      }
    }

    return { raw: null, parsed: null, source: "pot-unavailable" };
  }

  function readHeroStack() {
    const gateway = document.querySelector('[class*="playerMeGateway"]');
    if (gateway) {
      for (const el of gateway.querySelectorAll("span, div, p")) {
        const text = textOf(el);
        if (!text || !/\$/.test(text) || /\bPOT\b/i.test(text)) continue;
        const parsed = parseMoney(text);
        if (parsed !== null) return { raw: text, parsed, source: "playerMeGateway" };
      }
    }
    return { raw: null, parsed: null, source: "stack-unavailable" };
  }

  function readActionBar() {
    const scopes = [];
    const yourTurn = document.querySelector('[class*="yourTurn___"]');
    if (yourTurn) {
      scopes.push(yourTurn.closest('[class*="controls"]') || yourTurn.parentElement || yourTurn);
    }
    scopes.push(document.querySelector('[class*="controls"]'));
    scopes.push(getGameRoot());

    const buttons = [];
    const seen = new Set();

    for (const scope of scopes) {
      if (!scope || isInsideHelperPanel(scope)) continue;
      for (const el of scope.querySelectorAll("button, a, [role='button']")) {
        if (isInsideHelperPanel(el)) continue;
        if (el.disabled || el.getAttribute("aria-disabled") === "true") continue;
        const text = textOf(el);
        if (!text) continue;
        if (!/\b(fold|check|call|raise|bet)\b/i.test(text)) continue;
        const key = text.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        const rect = el.getBoundingClientRect();
        if (rect.width < 20 || rect.height < 10) continue;
        buttons.push({ text, left: rect.left, top: rect.top });
      }
    }

    buttons.sort((a, b) => a.left - b.left || a.top - b.top);

    let callRaw = "";
    let callAmount = null;
    let checkAvailable = false;

    for (const { text } of buttons) {
      if (/\bcheck\b/i.test(text)) {
        checkAvailable = true;
        callAmount = 0;
        callRaw = text;
        break;
      }
      if (/\bcall\s+any\b/i.test(text)) {
        checkAvailable = true;
        callAmount = 0;
        callRaw = text;
        break;
      }
    }

    if (!checkAvailable) {
      for (const { text } of buttons) {
        if (/\bcall\b/i.test(text) && !/\braise\b/i.test(text)) {
          callRaw = text;
          callAmount = parseMoney(text);
          break;
        }
      }
    }

    if (callAmount === null && !checkAvailable) {
      checkAvailable = buttons.length === 0;
    }

    const heroTurn = Boolean(yourTurn) || buttons.length > 0;
    const canRaise = buttons.some((b) => /\b(raise|bet)\b/i.test(b.text));
    const canFold = buttons.some((b) => /\bfold\b/i.test(b.text));

    return {
      buttons,
      callRaw,
      callAmount,
      checkAvailable: checkAvailable || callAmount === 0,
      heroTurn,
      canRaise,
      canFold,
    };
  }

  // --- Preflop multi-way thresholds ---

  function preflopThresholds(activePlayers) {
    const n = Math.max(2, Math.min(10, activePlayers || 2));
    const tightness = (n - 2) / 8;
    return {
      players: n,
      foldBelow: 0.18 + tightness * 0.14,
      callMin: 0.32 + tightness * 0.14,
      raiseMin: 0.52 + tightness * 0.16,
    };
  }

  function computeMetrics(helper, torn) {
    const winProb = parsePercent(helper.winProbRaw);
    const pot = torn.pot.parsed;
    const callAmount = torn.actions.callAmount;
    const heroStack = torn.stack.parsed;
    const checkAvailable = torn.actions.checkAvailable;
    const potAvailable = pot !== null;

    let potOdds = null;
    if (potAvailable && callAmount !== null && callAmount > 0 && pot + callAmount > 0) {
      potOdds = callAmount / (pot + callAmount);
    }

    let spr = null;
    if (potAvailable && pot > 0 && heroStack !== null) {
      spr = heroStack / pot;
    }

    let ev = null;
    if (potAvailable && winProb !== null && callAmount !== null && callAmount > 0) {
      ev = winProb * pot - (1 - winProb) * callAmount;
    }

    return {
      winProb,
      pot,
      potAvailable,
      callAmount,
      checkAvailable,
      heroStack,
      potOdds,
      spr,
      ev,
      activePlayers: helper.activePlayers,
      isPreflop: helper.isPreflop,
      preflop: preflopThresholds(helper.activePlayers),
    };
  }

  function makeDecision(metrics, torn) {
    const {
      winProb,
      potAvailable,
      callAmount,
      checkAvailable,
      heroStack,
      potOdds,
      ev,
      spr,
      activePlayers,
      isPreflop,
      preflop,
    } = metrics;
    const { heroTurn, canRaise } = torn.actions;

    if (!torn.helper.helperPresent) {
      return { action: "WAIT", reason: "Install Torn Poker Helper (GreasyFork 538541)" };
    }

    if (!heroTurn) {
      return { action: "WAIT", reason: "Not your turn" };
    }

    if (winProb === null) {
      return { action: "WAIT", reason: "Waiting for Poker Helper win probability" };
    }

    const pct = (n) => `${Math.round(n * 100)}%`;
    const money = (n) => `$${Math.round(n).toLocaleString()}`;
    const tableCtx = activePlayers ? `${activePlayers}-way` : "multi-way";

    if (!potAvailable) {
      if (isPreflop) {
        if (winProb < preflop.foldBelow) {
          return {
            action: "FOLD",
            reason: `${pct(winProb)} vs ${tableCtx} preflop range — fold (${preflop.players} players)`,
          };
        }
        if (winProb >= preflop.raiseMin && canRaise) {
          return {
            action: "RAISE",
            reason: `${pct(winProb)} strong for ${tableCtx} open (${preflop.players} players, no pot yet)`,
          };
        }
        return {
          action: checkAvailable ? "CALL" : "WAIT",
          reason: `${pct(winProb)} playable ${tableCtx} preflop — pot not available yet`,
        };
      }
      return { action: "WAIT", reason: "Pot unavailable (pre-deal) — EV disabled" };
    }

    if (checkAvailable || callAmount === 0 || callAmount === null) {
      if (isPreflop) {
        if (winProb < preflop.foldBelow) {
          return {
            action: "FOLD",
            reason: `${pct(winProb)} below ${tableCtx} continue range (${preflop.players} players)`,
          };
        }
        if (winProb >= preflop.raiseMin && canRaise) {
          return {
            action: "RAISE",
            reason: `CHECK available — ${pct(winProb)} value raise ${tableCtx} (${preflop.players} players)`,
          };
        }
      }
      return {
        action: "CALL",
        reason: `CHECK available — ${pct(winProb)} equity${spr !== null ? `, SPR ${spr.toFixed(1)}` : ""}`,
      };
    }

    if (potOdds === null || ev === null) {
      return { action: "WAIT", reason: "Need call amount for pot-odds / EV" };
    }

    const stackCommit = heroStack !== null && callAmount > 0 && callAmount >= heroStack * 0.9;

    if (stackCommit) {
      if (ev > 0 && winProb >= potOdds) {
        return {
          action: "ALL-IN",
          reason: `+EV ${money(ev)} — ${pct(winProb)} vs ${pct(potOdds)} pot odds (${tableCtx})`,
        };
      }
      return {
        action: "FOLD",
        reason: `-EV ${money(Math.abs(ev))} — ${pct(winProb)} below ${pct(potOdds)} pot odds`,
      };
    }

    if (isPreflop && winProb < preflop.callMin && ev < 0) {
      return {
        action: "FOLD",
        reason: `-EV ${money(Math.abs(ev))} — ${pct(winProb)} tight for ${tableCtx} (${preflop.players} players)`,
      };
    }

    if (ev < 0) {
      return {
        action: "FOLD",
        reason: `-EV ${money(Math.abs(ev))} — ${pct(winProb)} vs ${pct(potOdds)} pot odds`,
      };
    }

    const raiseBar = isPreflop ? preflop.raiseMin : 0.68;
    if (winProb >= raiseBar && canRaise && (spr === null || spr > 3)) {
      return {
        action: "RAISE",
        reason: `${pct(winProb)} equity — value raise${spr !== null ? ` (SPR ${spr.toFixed(1)})` : ""} +EV ${money(ev)}`,
      };
    }

    return {
      action: "CALL",
      reason: `+EV ${money(ev)} — ${pct(winProb)} vs ${pct(potOdds)} pot odds (${tableCtx})`,
    };
  }

  // --- Overlay ---

  function ensureOverlay() {
    let el = document.getElementById(OVERLAY_ID);
    if (el) return el;

    el = document.createElement("div");
    el.id = OVERLAY_ID;
    el.setAttribute("data-torn-hud-v2", "1");
    el.style.cssText = [
      "position:fixed",
      "bottom:12px",
      "right:12px",
      "z-index:99998",
      "min-width:300px",
      "max-width:380px",
      "padding:10px 14px",
      "border-radius:10px",
      "background:rgba(12,18,28,0.94)",
      "border:1px solid rgba(100,160,255,0.35)",
      "box-shadow:0 6px 20px rgba(0,0,0,0.45)",
      "font:600 12px/1.4 'Segoe UI',system-ui,sans-serif",
      "color:#e8eef7",
      "pointer-events:none",
      "user-select:none",
    ].join(";");
    el.innerHTML = `
      <div style="font-size:10px;letter-spacing:0.08em;color:#7a9cc6;margin-bottom:4px;">TORN HUD V2</div>
      <div id="torn-hud-v2-context" style="font-size:10px;color:#8fa8c4;margin-bottom:6px;">—</div>
      <div id="torn-hud-v2-metrics" style="font-family:'Courier New',monospace;font-size:11px;color:#b8cfe8;margin-bottom:6px;">—</div>
      <div id="torn-hud-v2-decision" style="font-size:15px;font-weight:700;color:#5dade2;">WAIT</div>
      <div id="torn-hud-v2-reason" style="font-size:11px;font-weight:400;color:#95a8bc;margin-top:4px;">Starting…</div>
    `;
    document.body.appendChild(el);
    return el;
  }

  const ACTION_COLORS = {
    WAIT: "#95a5a6",
    FOLD: "#e74c3c",
    CALL: "#2ecc71",
    RAISE: "#f39c12",
    "ALL-IN": "#e67e22",
  };

  function updateOverlay(metrics, decision, torn) {
    const root = ensureOverlay();
    const contextEl = root.querySelector("#torn-hud-v2-context");
    const metricsEl = root.querySelector("#torn-hud-v2-metrics");
    const decisionEl = root.querySelector("#torn-hud-v2-decision");
    const reasonEl = root.querySelector("#torn-hud-v2-reason");

    const fmtPct = (v) => (v === null ? "—" : `${Math.round(v * 100)}%`);
    const fmtNum = (v) => (v === null ? "—" : v.toFixed(1));
    const fmtEv = (v) => {
      if (v === null) return "—";
      const sign = v >= 0 ? "+" : "";
      return `${sign}$${Math.round(v)}`;
    };
    const fmtPot = metrics.potAvailable ? `$${metrics.pot.toLocaleString()}` : "—";
    const fmtCall =
      metrics.checkAvailable || metrics.callAmount === 0
        ? "CHECK available"
        : metrics.callAmount !== null
          ? `$${metrics.callAmount.toLocaleString()}`
          : "—";

    const playersLabel = metrics.activePlayers ? `${metrics.activePlayers} players` : "— players";
    contextEl.textContent = `${playersLabel} | Pot ${fmtPot} | ${metrics.checkAvailable ? "CHECK available" : `Call ${fmtCall}`}`;

    metricsEl.textContent = `Pot Odds ${fmtPct(metrics.potOdds)} | SPR ${fmtNum(metrics.spr)} | EV ${fmtEv(metrics.ev)}`;
    decisionEl.textContent = decision.action;
    decisionEl.style.color = ACTION_COLORS[decision.action] || "#5dade2";
    reasonEl.textContent = decision.reason;
  }

  function fingerprint(state) {
    return JSON.stringify(state);
  }

  function tick() {
    const helper = readPokerHelperState();
    const torn = {
      helper,
      pot: readPot(),
      stack: readHeroStack(),
      actions: readActionBar(),
    };

    const metrics = computeMetrics(helper, torn);
    const decision = makeDecision(metrics, torn);

    const fp = fingerprint({
      heroCards: helper.heroCards,
      boardCards: helper.boardCards,
      winProbRaw: helper.winProbRaw,
      activePlayers: helper.activePlayers,
      pot: metrics.pot,
      callAmount: metrics.callAmount,
      checkAvailable: metrics.checkAvailable,
      decision: decision.action,
    });

    if (fp !== lastFingerprint) {
      lastFingerprint = fp;
      updateOverlay(metrics, decision, torn);
    }
  }

  function boot() {
    ensureOverlay();
    tick();

    pollTimer = window.setInterval(tick, POLL_MS);

    const roots = [getGameRoot(), getHelperPanel()].filter(Boolean);
    observer = new MutationObserver(() => tick());
    for (const root of roots) {
      observer.observe(root, {
        childList: true,
        subtree: true,
        characterData: true,
        attributes: true,
      });
    }

    console.info("[torn-hud-v2] Decision engine — Poker Helper HUD + Torn pot/stack/actions. No network.");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
