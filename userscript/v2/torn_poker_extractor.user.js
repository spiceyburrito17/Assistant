// ==UserScript==
// @name         Torn Poker HUD v2 Extractor
// @namespace    torn-hud-v2
// @version      0.3.0
// @description  Passive DOM extractor for live Torn poker — Phase 2 calibration
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
  const DEBOUNCE_MS = 150;
  const POLL_MS = 500;

  const DEBUG =
    localStorage.getItem("torn_hud_v2_debug") === "1" ||
    new URLSearchParams(location.search).get("hud_debug") === "1";

  const SUIT_MAP = { clubs: "c", spades: "s", hearts: "h", diamonds: "d" };

  /** Stable structural anchors — see userscript/v2/selectors.md */
  const ANCHORS = {
    root: ["#mainPokerBox", '[class*="pokerTable"]', '[class*="tableWrapper"]', "main"],
    potClass: ['[class*="pot"]', '[class*="totalPot"]', '[class*="potAmount"]'],
    community: ['[class*="communityCards"]'],
    hand: ['[class*="hand"]'],
    cardFront: ['[class*="front"] > div[role="img"]', 'div[role="img"][class*="card"]'],
    heroSeat: ['[id^="player-"]', '[class*="playerWrapper"]', '[class*="opponent"]'],
    yourTurn: ['[class*="yourTurn"]'],
    controls: ['[class*="controls"]', '[class*="action"]', '[class*="buttons"]'],
    playerCardsData: ["[data-player-cards]"],
    boardCardsData: ["[data-board-cards]"],
  };

  let socket = null;
  let reconnectAttempt = 0;
  let reconnectTimer = null;
  let pollTimer = null;
  let observer = null;
  let debounceTimer = null;
  let seq = 0;
  let lastFingerprint = "";

  function logGroup(title, fn) {
    if (!DEBUG) return fn();
    console.group(`[torn-hud-v2][calibration] ${title}`);
    try {
      fn();
    } finally {
      console.groupEnd();
    }
  }

  function textOf(node) {
    return (node?.textContent || "").replace(/\s+/g, " ").trim();
  }

  function queryFirst(selectors, root = document) {
    for (const selector of selectors) {
      try {
        const node = root.querySelector(selector);
        if (node) return node;
      } catch (_err) {
        /* invalid selector on some pages */
      }
    }
    return null;
  }

  function queryAll(selectors, root = document) {
    for (const selector of selectors) {
      try {
        const nodes = root.querySelectorAll(selector);
        if (nodes.length) return Array.from(nodes);
      } catch (_err) {
        /* ignore */
      }
    }
    return [];
  }

  function findRoot() {
    return queryFirst(ANCHORS.root) || document.body;
  }

  function parseMoney(raw) {
    if (!raw) return null;
    const cleaned = String(raw).replace(/,/g, "");
    const match = cleaned.match(/(\d+(?:\.\d+)?)\s*([kKmM])?/);
    if (!match) return null;
    let value = Number.parseFloat(match[1]);
    const suffix = match[2]?.toUpperCase();
    if (suffix === "K") value *= 1000;
    if (suffix === "M") value *= 1000000;
    return Number.isFinite(value) ? Math.round(value) : null;
  }

  function cardFromTornClass(className) {
    const match = String(className || "").match(/(clubs|spades|hearts|diamonds)-([0-9TJQKA]+)/i);
    if (!match) return null;
    const rank = match[2] === "10" ? "T" : match[2].toUpperCase();
    return `${rank}${SUIT_MAP[match[1].toLowerCase()]}`;
  }

  function cardFromElement(el) {
    const fromClass = cardFromTornClass(el.className);
    if (fromClass) return fromClass;
    const aria = el.getAttribute("aria-label") || "";
    if (/card face down/i.test(aria)) return null;
    const compact = aria.replace(/[^2-9TJQKAcdhs]/gi, "").toUpperCase();
    if (/^([2-9TJQKA]|10)[CDHS]$/.test(compact)) {
      const rank = compact.startsWith("10") ? "T" : compact[0];
      return `${rank}${compact.slice(-1).toLowerCase()}`;
    }
    for (const candidate of [el.dataset?.card, el.dataset?.value, el.getAttribute("title"), el.textContent]) {
      const parsed = cardFromTornClass(candidate) || normalizePlainCard(candidate);
      if (parsed) return parsed;
    }
    return null;
  }

  function normalizePlainCard(raw) {
    if (!raw) return null;
    const compact = String(raw).trim().toUpperCase().replace(/\s+/g, "");
    if (/^([2-9TJQKA]|10)[CDHS]$/.test(compact)) {
      const rank = compact.startsWith("10") ? "T" : compact[0];
      return `${rank}${compact.slice(-1).toLowerCase()}`;
    }
    return null;
  }

  function isFaceUpCard(el) {
    const aria = el.getAttribute("aria-label") || "";
    return aria !== "card face down" && !/face down/i.test(aria);
  }

  function extractHeroCards(root) {
    const sources = [];
    const cards = [];
    const seen = new Set();

    const dataNode = queryFirst(ANCHORS.playerCardsData, root);
    if (dataNode) {
      sources.push("hero:data-player-cards");
      for (const card of scrapeCardsFromNode(dataNode)) {
        pushCard(cards, seen, card);
      }
    }

    const handNodes = queryAll(ANCHORS.hand, root);
    for (const hand of handNodes) {
      if (hand.closest('[class*="communityCards"]')) continue;
      const imgs = hand.querySelectorAll('[class*="front"] > div[role="img"], div[role="img"]');
      for (const img of imgs) {
        if (!isFaceUpCard(img)) continue;
        const card = cardFromElement(img);
        if (card) {
          sources.push("hero:hand-face-up");
          pushCard(cards, seen, card);
        }
      }
    }

    return { cards, source: sources[0] || "hero:none", candidates: handNodes.length };
  }

  function extractBoardCards(root) {
    const sources = [];
    const cards = [];
    const seen = new Set();

    const dataNode = queryFirst(ANCHORS.boardCardsData, root);
    if (dataNode) {
      sources.push("board:data-board-cards");
      for (const card of scrapeCardsFromNode(dataNode)) {
        pushCard(cards, seen, card);
      }
    }

    for (const community of queryAll(ANCHORS.community, root)) {
      const imgs = community.querySelectorAll('[class*="front"] > div[role="img"], div[role="img"]');
      for (const img of imgs) {
        if (!isFaceUpCard(img)) continue;
        const card = cardFromElement(img);
        if (card) {
          sources.push("board:community-face-up");
          pushCard(cards, seen, card);
        }
      }
    }

    return { cards, source: sources[0] || "board:none", candidates: cards.length };
  }

  function scrapeCardsFromNode(node) {
    const out = [];
    const seen = new Set();
    for (const el of node.querySelectorAll('[role="img"], [data-card], [class*="card"]')) {
      const card = cardFromElement(el);
      if (card && !seen.has(card)) {
        out.push(card);
        seen.add(card);
      }
    }
    return out;
  }

  function pushCard(list, seen, card) {
    if (!card || seen.has(card)) return;
    list.push(card);
    seen.add(card);
  }

  function findHeroZone(root) {
    for (const hand of queryAll(ANCHORS.hand, root)) {
      if (hand.closest('[class*="communityCards"]')) continue;
      const faceUp = hand.querySelector('[class*="front"] > div[role="img"]:not([aria-label="card face down"])');
      if (faceUp) {
        return (
          hand.closest('[id^="player-"]') ||
          hand.closest('[class*="playerWrapper"]') ||
          hand.closest('[class*="opponent"]') ||
          hand.parentElement
        );
      }
    }
    const yourTurn = queryFirst(ANCHORS.yourTurn, root);
    if (yourTurn) {
      return (
        yourTurn.closest('[id^="player-"]') ||
        yourTurn.closest('[class*="playerWrapper"]') ||
        yourTurn.parentElement
      );
    }
    return null;
  }

  function extractPot(root) {
    const candidates = [];

    for (const selector of ANCHORS.potClass) {
      for (const node of root.querySelectorAll(selector)) {
        const text = textOf(node);
        if (text) candidates.push({ strategy: "class", selector, text, node });
      }
    }

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const text = textOf(walker.currentNode);
      if (!/\bPOT\b/i.test(text)) continue;
      candidates.push({ strategy: "text-anchor", text, node: walker.currentNode.parentElement });
    }

    for (const candidate of candidates) {
      const parsed = parseMoney(candidate.text);
      if (parsed !== null || /\$/.test(candidate.text)) {
        return {
          raw: candidate.text,
          parsed,
          source: candidate.strategy,
          candidates: candidates.slice(0, 8),
        };
      }
    }

    return { raw: null, parsed: null, source: "pot:none", candidates };
  }

  function extractHeroStack(root) {
    const heroZone = findHeroZone(root);
    const candidates = [];
    if (!heroZone) {
      return { raw: null, parsed: null, source: "stack:no-hero-zone", candidates };
    }

    for (const el of heroZone.querySelectorAll("span, div, p")) {
      const text = textOf(el);
      if (!text || !/\$/.test(text)) continue;
      if (/\bPOT\b/i.test(text)) continue;
      candidates.push({ text, node: el });
    }

    candidates.sort((a, b) => parseMoney(b.text) - parseMoney(a.text));
    const best = candidates[0];
    if (!best) {
      return { raw: null, parsed: null, source: "stack:none", candidates };
    }
    return {
      raw: best.text,
      parsed: parseMoney(best.text),
      source: "stack:hero-zone-money",
      candidates: candidates.slice(0, 5),
    };
  }

  function extractActionButtons(root) {
    const candidates = [];
    const yourTurn = queryFirst(ANCHORS.yourTurn, root);
    const scopes = [];

    if (yourTurn) scopes.push(yourTurn.closest('[class*="controls"]') || yourTurn.parentElement || yourTurn);
    scopes.push(queryFirst(ANCHORS.controls, root));
    scopes.push(root);

    for (const scope of scopes) {
      if (!scope) continue;
      for (const el of scope.querySelectorAll("button, a, [role='button']")) {
        if (el.disabled || el.getAttribute("aria-disabled") === "true") continue;
        const text = textOf(el);
        if (!text) continue;
        if (!/\b(fold|check|call|raise|bet|show cards|sit out|leave)\b/i.test(text)) continue;
        const rect = el.getBoundingClientRect();
        if (rect.width < 20 || rect.height < 10) continue;
        candidates.push({ text, el, left: rect.left, top: rect.top });
      }
    }

    const deduped = [];
    const seenText = new Set();
    candidates
      .sort((a, b) => a.left - b.left || a.top - b.top)
      .forEach((item) => {
        const key = item.text.toLowerCase();
        if (seenText.has(key)) return;
        seenText.add(key);
        deduped.push(item);
      });

    return deduped;
  }

  function classifySlotText(text) {
    const lowered = text.toLowerCase();
    if (/\bshow\s+cards\b|\bsit\s+out\b|\bleave\b/i.test(lowered)) return null;
    if (/\bfold\b/.test(lowered)) return "fold";
    if (/\bcall\s+any\b/.test(lowered)) return "check";
    if (/\bcheck\b/.test(lowered)) return "check";
    if (/\braise\b/.test(lowered)) return "raise";
    if (/\bbet\b/.test(lowered)) return "bet";
    if (/\bcall\b/.test(lowered)) return "call";
    return null;
  }

  function extractActionSlots(root) {
    const buttons = extractActionButtons(root);
    const slots = {
      left: buttons[0]?.text || "",
      centre: buttons[1]?.text || "",
      right: buttons[2]?.text || "",
    };

    const labels = [];
    const seen = new Set();
    for (const text of [slots.left, slots.centre, slots.right]) {
      const label = classifySlotText(text);
      if (label && !seen.has(label)) {
        labels.push(label);
        seen.add(label);
      }
    }

    return { slots, labels, buttons, source: "actions:sorted-buttons" };
  }

  function extractPostHand(root) {
    const labels = [];
    const candidates = [];

    for (const el of root.querySelectorAll("button, a, [role='button'], span, div")) {
      const text = textOf(el).toUpperCase();
      if (!text) continue;
      for (const label of ["SHOW CARDS", "SIT OUT", "LEAVE"]) {
        if (text.includes(label) && !labels.includes(label)) {
          labels.push(label);
          candidates.push({ label, text: textOf(el) });
        }
      }
    }

    return { labels, postHandUi: labels.length > 0, candidates };
  }

  function extractHeroTurn(root, actionLabels, postHandUi) {
    if (postHandUi) return false;
    if (queryFirst(ANCHORS.yourTurn, root)) return true;
    return actionLabels.length > 0;
  }

  function amountToCallFromSlots(slots) {
    for (const text of [slots.centre, slots.left, slots.right]) {
      if (!text) continue;
      if (/\bcall\s+any\b/i.test(text)) return { raw: text, parsed: 0 };
      if (/\bcall\b/i.test(text)) return { raw: text, parsed: parseMoney(text) };
    }
    return { raw: null, parsed: null };
  }

  function streetHint(boardCards) {
    if (boardCards.length >= 5) return "river";
    if (boardCards.length === 4) return "turn";
    if (boardCards.length === 3) return "flop";
    if (boardCards.length > 0) return "unknown";
    return "preflop";
  }

  function scrapeState() {
    const root = findRoot();
    let pot = {};
    let hero = {};
    let board = {};
    let stack = {};
    let actions = {};
    let postHand = {};

    logGroup("pot", () => {
      pot = extractPot(root);
      if (DEBUG) console.log("candidates", pot.candidates, "selected", { raw: pot.raw, parsed: pot.parsed });
    });

    logGroup("hero_cards", () => {
      hero = extractHeroCards(root);
      if (DEBUG) console.log("selected", hero.cards, "candidates", hero.candidates);
    });

    logGroup("board_cards", () => {
      board = extractBoardCards(root);
      if (DEBUG) console.log("selected", board.cards, "candidates", board.candidates);
    });

    logGroup("hero_stack", () => {
      stack = extractHeroStack(root);
      if (DEBUG) console.log("candidates", stack.candidates, "selected", { raw: stack.raw, parsed: stack.parsed });
    });

    logGroup("action_slots", () => {
      actions = extractActionSlots(root);
      if (DEBUG) {
        console.log("buttons", actions.buttons);
        console.log("slots", actions.slots);
        console.log("labels", actions.labels);
      }
    });

    logGroup("post_hand", () => {
      postHand = extractPostHand(root);
      if (DEBUG) console.log("labels", postHand.labels, "candidates", postHand.candidates);
    });

    const heroTurn = extractHeroTurn(root, actions.labels, postHand.postHandUi);
    const callAmount = amountToCallFromSlots(actions.slots);
    const extractSources = [
      `pot=${pot.source}`,
      `hero=${hero.source}`,
      `board=${board.source}`,
      `stack=${stack.source}`,
      `actions=${actions.source}`,
    ].join(";");

    return {
      schema_version: SCHEMA_VERSION,
      message_type: "table_delta",
      seq: ++seq,
      ts_ms: Date.now(),
      source_url: location.href,
      pot_raw: pot.raw,
      pot_parsed: pot.parsed,
      hero_cards: hero.cards,
      board_cards: board.cards,
      hero_stack_raw: stack.raw,
      hero_stack_parsed: stack.parsed,
      hero_turn: heroTurn,
      slot_left_raw: actions.slots.left,
      slot_centre_raw: actions.slots.centre,
      slot_right_raw: actions.slots.right,
      amount_to_call_raw: callAmount.raw,
      amount_to_call_parsed: callAmount.parsed,
      legal_actions: heroTurn ? actions.labels : [],
      post_hand_ui: postHand.postHandUi,
      post_hand_labels: postHand.labels,
      street_hint: streetHint(board.cards),
      extract_sources: extractSources,
    };
  }

  function fingerprint(state) {
    return JSON.stringify({
      pot_parsed: state.pot_parsed,
      pot_raw: state.pot_raw,
      hero_cards: state.hero_cards,
      board_cards: state.board_cards,
      hero_stack_parsed: state.hero_stack_parsed,
      hero_turn: state.hero_turn,
      legal_actions: state.legal_actions,
      slots: [state.slot_left_raw, state.slot_centre_raw, state.slot_right_raw],
      post_hand_ui: state.post_hand_ui,
      post_hand_labels: state.post_hand_labels,
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
    if (DEBUG) console.info("[torn-hud-v2] delta", state);
    send(state);
  }

  function schedulePublish() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      debounceTimer = null;
      publishIfChanged();
    }, DEBOUNCE_MS);
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
      console.info("[torn-hud-v2] connected to", WS_URL);
      send({
        schema_version: SCHEMA_VERSION,
        message_type: "hello",
        seq: ++seq,
        ts_ms: Date.now(),
        source_url: location.href,
      });
      publishIfChanged();
    });
    socket.addEventListener("close", scheduleReconnect);
    socket.addEventListener("error", () => socket.close());
  }

  function boot() {
    connect();
    const root = findRoot();
    observer = new MutationObserver(() => schedulePublish());
    observer.observe(root, { childList: true, subtree: true, characterData: true, attributes: true });
    pollTimer = window.setInterval(schedulePublish, POLL_MS);
    schedulePublish();
    console.info(
      `[torn-hud-v2] passive DOM extractor active${DEBUG ? " (debug mode ON)" : ""}. ` +
        "Set localStorage.torn_hud_v2_debug='1' to calibrate."
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
