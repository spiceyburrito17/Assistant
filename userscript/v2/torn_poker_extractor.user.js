// ==UserScript==
// @name         Torn Poker HUD v2 Extractor
// @namespace    torn-hud-v2
// @version      0.2.0
// @description  Passive DOM extractor for Torn poker — sends structured table deltas to localhost HUD
// @match        https://www.torn.com/poker*
// @match        https://www.torn.com/page.php?sid=poker*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function tornHudV2Extractor() {
  "use strict";

  const SCHEMA_VERSION = 1;
  const WS_URL = "ws://localhost:8765";
  const RECONNECT_BASE_MS = 500;
  const RECONNECT_MAX_MS = 10000;
  const POLL_MS = 250;

  /** Calibrate against live Torn poker DOM. No HTML/CSS injection. Read-only. */
  const SELECTORS = {
    root: ["#poker-root", ".poker-table", "[data-poker-root]", "main"],
    pot: ["[data-pot]", ".pot-amount", ".poker-pot", ".pot-value", "*[class*='pot']"],
    heroCards: ["[data-hero-cards] .card", ".player-cards.hero .card", ".hero-cards .card", ".your-cards .card"],
    boardCards: ["[data-board-cards] .card", ".community-cards .card", ".board-cards .card", ".table-cards .card"],
    heroStack: ["[data-hero-stack]", ".hero-stack", ".player-stack", "*[class*='stack']"],
    actionBar: ["[data-action-bar]", ".poker-actions", ".action-buttons", ".player-actions"],
    actionSlots: [
      "[data-action-slot-left]",
      "[data-action-slot-centre]",
      "[data-action-slot-right]",
      ".action-slot-left",
      ".action-slot-centre",
      ".action-slot-right",
    ],
    postHand: ["[data-post-hand]", ".post-hand-actions", ".show-cards-panel"],
  };

  let socket = null;
  let reconnectAttempt = 0;
  let reconnectTimer = null;
  let pollTimer = null;
  let observer = null;
  let seq = 0;
  let lastFingerprint = "";

  function queryFirst(selectors, root = document) {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      if (node) return node;
    }
    return null;
  }

  function queryAll(selectors, root = document) {
    for (const selector of selectors) {
      const nodes = root.querySelectorAll(selector);
      if (nodes.length) return Array.from(nodes);
    }
    return [];
  }

  function textOf(node) {
    return (node?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function parseMoney(raw) {
    if (!raw) return null;
    const match = String(raw).replace(/,/g, "").match(/(\d+(?:\.\d+)?)([kKmM])?/);
    if (!match) return null;
    let value = Number.parseFloat(match[1]);
    const suffix = match[2]?.toUpperCase();
    if (suffix === "K") value *= 1000;
    if (suffix === "M") value *= 1000000;
    return Number.isFinite(value) ? Math.round(value) : null;
  }

  function normalizeCard(raw) {
    if (!raw) return null;
    const compact = String(raw).trim().toUpperCase().replace(/\s+/g, "");
    if (/^([2-9TJQKA]|10)[CDHS]$/.test(compact)) {
      const rank = compact.startsWith("10") ? "T" : compact[0];
      return `${rank}${compact.slice(-1).toLowerCase()}`;
    }
    return null;
  }

  function cardFromElement(el) {
    const candidates = [el.dataset?.card, el.dataset?.value, el.getAttribute("alt"), el.getAttribute("title"), el.textContent];
    for (const candidate of candidates) {
      const card = normalizeCard(candidate);
      if (card) return card;
    }
    return null;
  }

  function scrapeCards(selectors, root) {
    const out = [];
    const seen = new Set();
    for (const el of queryAll(selectors, root)) {
      const card = cardFromElement(el);
      if (card && !seen.has(card)) {
        out.push(card);
        seen.add(card);
      }
    }
    return out;
  }

  function detectLegalActions(root) {
    const bar = queryFirst(SELECTORS.actionBar, root) || root;
    const labels = [];
    const seen = new Set();
    for (const button of bar.querySelectorAll("button, a, [role='button']")) {
      if (button.disabled || button.getAttribute("aria-disabled") === "true") continue;
      const text = textOf(button).toLowerCase();
      for (const label of ["fold", "check", "call", "raise", "bet"]) {
        if (new RegExp(`\\b${label}\\b`).test(text) && !seen.has(label)) {
          labels.push(label);
          seen.add(label);
        }
      }
    }
    return labels;
  }

  function scrapeActionSlots(root) {
    const bar = queryFirst(SELECTORS.actionBar, root) || root;
    const buttons = bar.querySelectorAll("button, a, [role='button']");
    const texts = Array.from(buttons).map((node) => textOf(node)).filter(Boolean);
    return {
      left: texts[0] || "",
      centre: texts[1] || "",
      right: texts[2] || "",
    };
  }

  function detectPostHand(root) {
    const labels = [];
    for (const el of queryAll(SELECTORS.postHand, root)) {
      const text = textOf(el).toUpperCase();
      for (const label of ["SHOW CARDS", "SIT OUT", "LEAVE"]) {
        if (text.includes(label) && !labels.includes(label)) labels.push(label);
      }
    }
    return labels;
  }

  function scrapeState() {
    const root = queryFirst(SELECTORS.root) || document.body;
    const potNode = queryFirst(SELECTORS.pot, root);
    const stackNode = queryFirst(SELECTORS.heroStack, root);
    const slots = scrapeActionSlots(root);
    const postHandLabels = detectPostHand(root);
    const legalActions = detectLegalActions(root);
    const heroTurn = legalActions.length > 0 && postHandLabels.length === 0;

    let amountToCallRaw = null;
    for (const text of [slots.centre, slots.left, slots.right]) {
      if (/\bcall\b/i.test(text)) {
        amountToCallRaw = text;
        break;
      }
    }

    return {
      schema_version: SCHEMA_VERSION,
      message_type: "table_delta",
      seq: ++seq,
      ts_ms: Date.now(),
      source_url: location.href,
      pot_raw: textOf(potNode) || null,
      pot_parsed: parseMoney(textOf(potNode)),
      hero_cards: scrapeCards(SELECTORS.heroCards, root),
      board_cards: scrapeCards(SELECTORS.boardCards, root),
      hero_stack_raw: textOf(stackNode) || null,
      hero_stack_parsed: parseMoney(textOf(stackNode)),
      hero_turn: heroTurn,
      slot_left_raw: slots.left,
      slot_centre_raw: slots.centre,
      slot_right_raw: slots.right,
      amount_to_call_raw: amountToCallRaw,
      amount_to_call_parsed: parseMoney(amountToCallRaw),
      legal_actions: heroTurn ? legalActions : [],
      post_hand_ui: postHandLabels.length > 0,
      post_hand_labels: postHandLabels,
      street_hint: null,
    };
  }

  function fingerprint(state) {
    return JSON.stringify({
      pot_parsed: state.pot_parsed,
      hero_cards: state.hero_cards,
      board_cards: state.board_cards,
      hero_turn: state.hero_turn,
      legal_actions: state.legal_actions,
      slots: [state.slot_left_raw, state.slot_centre_raw, state.slot_right_raw],
      post_hand_ui: state.post_hand_ui,
    });
  }

  function send(payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify(payload));
  }

  function publishIfChanged() {
    const state = scrapeState();
    const fp = fingerprint(state);
    if (fp === lastFingerprint) return;
    lastFingerprint = fp;
    send(state);
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    const delay = Math.min(RECONNECT_BASE_MS * 2 ** reconnectAttempt, RECONNECT_MAX_MS);
    reconnectAttempt += 1;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
    socket = new WebSocket(WS_URL);
    socket.addEventListener("open", () => {
      reconnectAttempt = 0;
      send({ schema_version: SCHEMA_VERSION, message_type: "hello", seq: ++seq, ts_ms: Date.now(), source_url: location.href });
      publishIfChanged();
    });
    socket.addEventListener("close", scheduleReconnect);
    socket.addEventListener("error", () => socket.close());
  }

  function boot() {
    connect();
    const root = queryFirst(SELECTORS.root) || document.body;
    observer = new MutationObserver(() => publishIfChanged());
    observer.observe(root, { childList: true, subtree: true, characterData: true, attributes: true });
    pollTimer = window.setInterval(publishIfChanged, POLL_MS);
    publishIfChanged();
    console.info("[torn-hud-v2] passive DOM extractor active");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
