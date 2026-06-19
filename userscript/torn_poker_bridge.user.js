// ==UserScript==
// @name         Torn Poker HUD Bridge
// @namespace    torn-accessibility-hud
// @version      0.1.0
// @description  Stream deterministic Torn poker table state to the local torn-hud WebSocket bridge
// @match        https://www.torn.com/poker*
// @match        https://www.torn.com/page.php?sid=poker*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function tornPokerBridge() {
  "use strict";

  const WS_URL = "ws://localhost:8765";
  const RECONNECT_BASE_MS = 500;
  const RECONNECT_MAX_MS = 10_000;
  const POLL_INTERVAL_MS = 250;
  const HEARTBEAT_INTERVAL_MS = 15_000;

  /**
   * Calibrate these selectors against the live Torn poker DOM.
   * The scraper tries each selector in order and uses the first match.
   */
  const SELECTORS = {
    root: ["#poker-root", ".poker-table", "[data-poker-root]", "main"],
    pot: [
      "[data-pot]",
      ".pot-amount",
      ".poker-pot",
      ".pot-value",
      "*[class*='pot']",
    ],
    heroCards: [
      "[data-hero-cards] .card",
      ".player-cards.hero .card",
      ".hero-cards .card",
      ".your-cards .card",
    ],
    boardCards: [
      "[data-board-cards] .card",
      ".community-cards .card",
      ".board-cards .card",
      ".table-cards .card",
    ],
    callAmount: [
      "[data-call-amount]",
      ".action-call .amount",
      ".call-amount",
      "button.call .amount",
    ],
    actionBar: [
      "[data-action-bar]",
      ".poker-actions",
      ".action-buttons",
      ".player-actions",
    ],
    heroTurnMarker: [
      "[data-hero-turn='true']",
      ".action-bar.active",
      ".poker-actions:not(.disabled)",
      ".your-turn",
    ],
  };

  const RANK_MAP = {
    ace: "A",
    a: "A",
    king: "K",
    k: "K",
    queen: "Q",
    q: "Q",
    jack: "J",
    j: "J",
    ten: "T",
    t: "T",
    "10": "T",
  };

  const SUIT_MAP = {
    clubs: "c",
    club: "c",
    c: "c",
    "♣": "c",
    diamonds: "d",
    diamond: "d",
    d: "d",
    "♦": "d",
    hearts: "h",
    heart: "h",
    h: "h",
    "♥": "h",
    spades: "s",
    spade: "s",
    s: "s",
    "♠": "s",
  };

  let socket = null;
  let reconnectAttempt = 0;
  let reconnectTimer = null;
  let pollTimer = null;
  let heartbeatTimer = null;
  let observer = null;
  let lastFingerprint = "";

  function queryFirst(selectors, root = document) {
    for (const selector of selectors) {
      const node = root.querySelector(selector);
      if (node) {
        return node;
      }
    }
    return null;
  }

  function queryAll(selectors, root = document) {
    for (const selector of selectors) {
      const nodes = root.querySelectorAll(selector);
      if (nodes.length > 0) {
        return Array.from(nodes);
      }
    }
    return [];
  }

  function parseMoney(raw) {
    if (raw == null) {
      return null;
    }
    const text = String(raw).trim().replace(/,/g, "");
    if (!text) {
      return null;
    }
    const match = text.match(/(\d+(?:\.\d+)?)([kKmM])?/);
    if (!match) {
      return null;
    }
    let value = Number.parseFloat(match[1]);
    const suffix = match[2]?.toUpperCase();
    if (suffix === "K") {
      value *= 1000;
    } else if (suffix === "M") {
      value *= 1_000_000;
    }
    return Number.isFinite(value) ? Math.round(value) : null;
  }

  function normalizeCard(raw) {
    if (!raw) {
      return null;
    }
    const compact = String(raw).trim();
    if (/^([2-9TJQKA]|10)[cdhs]$/i.test(compact)) {
      const rank = compact.startsWith("10") ? "T" : compact[0].toUpperCase();
      return `${rank}${compact.slice(-1).toLowerCase()}`;
    }

    const rankNode = compact.match(/([2-9jqka]|10|ace|king|queen|jack|ten)/i);
    const suitNode = compact.match(/(clubs?|diamonds?|hearts?|spades?|[cdhs♣♦♥♠])/i);
    if (!rankNode || !suitNode) {
      return null;
    }
    const rankKey = rankNode[1].toLowerCase();
    const suitKey = suitNode[1].toLowerCase();
    const rank = RANK_MAP[rankKey];
    const suit = SUIT_MAP[suitKey];
    if (!rank || !suit) {
      return null;
    }
    return `${rank}${suit}`;
  }

  function cardFromElement(element) {
    const datasetCard = element.dataset?.card || element.dataset?.value;
    if (datasetCard) {
      return normalizeCard(datasetCard);
    }
    const alt = element.getAttribute("alt") || element.getAttribute("title");
    if (alt) {
      return normalizeCard(alt);
    }
    const className = element.className || "";
    const classMatch = className.match(/(?:rank-([2-9tjqka]|10))?(?:suit-([cdhs]))?/i);
    if (classMatch && classMatch[1] && classMatch[2]) {
      return normalizeCard(`${classMatch[1]}${classMatch[2]}`);
    }
    return normalizeCard(element.textContent);
  }

  function scrapeCards(selectors, root) {
    const cards = [];
    const seen = new Set();
    for (const element of queryAll(selectors, root)) {
      const card = cardFromElement(element);
      if (card && !seen.has(card)) {
        cards.push(card);
        seen.add(card);
      }
    }
    return cards;
  }

  function detectLegalActions(root) {
    const actionRoot = queryFirst(SELECTORS.actionBar, root) || root;
    const labels = [];
    const seen = new Set();
    const buttons = actionRoot.querySelectorAll("button, a, [role='button']");
    for (const button of buttons) {
      const text = (button.textContent || "").trim().toLowerCase();
      if (!text || button.disabled || button.getAttribute("aria-disabled") === "true") {
        continue;
      }
      let label = null;
      if (/\bfold\b/.test(text)) {
        label = "fold";
      } else if (/\bcheck\b/.test(text)) {
        label = "check";
      } else if (/\bcall\b/.test(text)) {
        label = "call";
      } else if (/\braise\b/.test(text)) {
        label = "raise";
      } else if (/\bbet\b/.test(text)) {
        label = "bet";
      }
      if (label && !seen.has(label)) {
        labels.push(label);
        seen.add(label);
      }
    }
    return labels;
  }

  function scrapeTableState() {
    const root = queryFirst(SELECTORS.root) || document.body;
    const potNode = queryFirst(SELECTORS.pot, root);
    const callNode = queryFirst(SELECTORS.callAmount, root);
    const heroCards = scrapeCards(SELECTORS.heroCards, root);
    const boardCards = scrapeCards(SELECTORS.boardCards, root);
    const legalActions = detectLegalActions(root);
    const heroTurn =
      legalActions.length > 0 ||
      Boolean(queryFirst(SELECTORS.heroTurnMarker, root));

    let toCall = parseMoney(callNode?.textContent || callNode?.dataset?.amount);
    if (toCall == null && legalActions.includes("call")) {
      const callButton = Array.from(root.querySelectorAll("button, a, [role='button']")).find(
        (node) => /\bcall\b/i.test(node.textContent || "")
      );
      toCall = parseMoney(callButton?.textContent);
    }
    if (legalActions.includes("check") && !legalActions.includes("call")) {
      toCall = 0;
    }

    return {
      event: "table_update",
      pot: parseMoney(potNode?.textContent || potNode?.dataset?.amount),
      to_call: toCall,
      hero_cards: heroCards,
      board_cards: boardCards,
      hero_turn: heroTurn,
      legal_actions: heroTurn ? legalActions : [],
      ts: Date.now(),
      source_url: location.href,
    };
  }

  function fingerprint(state) {
    return JSON.stringify({
      pot: state.pot,
      to_call: state.to_call,
      hero_cards: state.hero_cards,
      board_cards: state.board_cards,
      hero_turn: state.hero_turn,
      legal_actions: state.legal_actions,
    });
  }

  function publishIfChanged(state) {
    const next = fingerprint(state);
    if (next === lastFingerprint) {
      return;
    }
    lastFingerprint = next;
    sendPayload(state);
  }

  function sendPayload(payload) {
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return;
    }
    try {
      socket.send(JSON.stringify(payload));
    } catch (error) {
      console.warn("[torn-hud-bridge] send failed", error);
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) {
      return;
    }
    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** reconnectAttempt,
      RECONNECT_MAX_MS
    );
    reconnectAttempt += 1;
    reconnectTimer = window.setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, delay);
  }

  function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }

    socket = new WebSocket(WS_URL);

    socket.addEventListener("open", () => {
      reconnectAttempt = 0;
      console.info("[torn-hud-bridge] connected to", WS_URL);
      sendPayload({ event: "ping", ts: Date.now(), source_url: location.href });
      publishIfChanged(scrapeTableState());
    });

    socket.addEventListener("close", () => {
      console.warn("[torn-hud-bridge] disconnected; reconnecting…");
      scheduleReconnect();
    });

    socket.addEventListener("error", () => {
      socket.close();
    });
  }

  function tick() {
    publishIfChanged(scrapeTableState());
  }

  function startHeartbeat() {
    heartbeatTimer = window.setInterval(() => {
      sendPayload({ event: "ping", ts: Date.now(), source_url: location.href });
    }, HEARTBEAT_INTERVAL_MS);
  }

  function observeDom() {
    const root = queryFirst(SELECTORS.root) || document.body;
    observer = new MutationObserver(() => {
      tick();
    });
    observer.observe(root, {
      childList: true,
      subtree: true,
      characterData: true,
      attributes: true,
    });
  }

  function boot() {
    connect();
    observeDom();
    pollTimer = window.setInterval(tick, POLL_INTERVAL_MS);
    startHeartbeat();
    tick();
    console.info("[torn-hud-bridge] DOM bridge active");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
