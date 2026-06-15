// ==UserScript==
// @name         Torn Poker HUD v2 Extractor
// @namespace    torn-hud-v2
// @version      0.3.1
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

  function describeEl(el) {
    if (!el) return "(null)";
    const tag = el.tagName?.toLowerCase() || "?";
    const id = el.id ? `#${el.id}` : "";
    const cls = el.className ? `.${String(el.className).split(/\s+/).slice(0, 2).join(".")}` : "";
    return `${tag}${id}${cls}`;
  }

  function logQueryCounts(label, selectors, root) {
    if (!DEBUG) return;
    console.group(`queries: ${label}`);
    for (const selector of selectors) {
      try {
        const nodes = root.querySelectorAll(selector);
        console.log(`  "${selector}" → ${nodes.length} element(s)`);
      } catch (err) {
        console.log(`  "${selector}" → ERROR: ${err.message}`);
      }
    }
    console.groupEnd();
  }

  function debugCardRejection(el) {
    const aria = el.getAttribute("aria-label") || "";
    if (/card face down/i.test(aria)) return "face_down_aria";
    const fromClass = cardFromTornClass(el.className);
    if (fromClass) return null;
    if (aria) {
      const compact = aria.replace(/[^2-9TJQKAcdhs]/gi, "").toUpperCase();
      if (/^([2-9TJQKA]|10)[CDHS]$/.test(compact)) return null;
      return `aria_unparseable:${aria.slice(0, 40)}`;
    }
    for (const field of ["dataset.card", "dataset.value", "title", "textContent"]) {
      const val = field.startsWith("dataset.")
        ? el.dataset?.[field.split(".")[1]]
        : field === "title"
          ? el.getAttribute("title")
          : el.textContent;
      if (val && (cardFromTornClass(val) || normalizePlainCard(val))) return null;
    }
    return `no_card_data class=${String(el.className || "").slice(0, 60)}`;
  }

  function debugLogPot(root) {
    const candidates = [];
    const audits = [];

    for (const selector of ANCHORS.potClass) {
      for (const node of root.querySelectorAll(selector)) {
        const text = textOf(node);
        const parsed = parseMoney(text);
        const dollarCount = (text.match(/\$/g) || []).length;
        const audit = {
          strategy: "class",
          selector,
          element: describeEl(node),
          text: text.slice(0, 120),
          parsed,
          dollarCount,
          childCount: node.childElementCount,
        };
        if (!text) {
          audit.verdict = "REJECT";
          audit.reason = "empty_text";
        } else if (parsed === null && !/\$/.test(text)) {
          audit.verdict = "REJECT";
          audit.reason = "no_money_pattern";
        } else if (dollarCount > 1) {
          audit.verdict = parsed !== null ? "SELECTED_BUT_SUSPICIOUS" : "REJECT";
          audit.reason = `multiple_dollar_signs(${dollarCount}) — likely parent wrapper with seat stacks concatenated`;
        } else {
          audit.verdict = "ACCEPT";
          audit.reason = parsed !== null ? "parseable_single_amount" : "has_dollar_sign";
        }
        audits.push(audit);
        if (text) candidates.push({ strategy: "class", selector, text, node });
      }
    }

    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const textNode = walker.currentNode;
      const text = textOf(textNode);
      if (!/\bPOT\b/i.test(text)) continue;
      const parent = textNode.parentElement;
      const parentText = textOf(parent);
      const parsed = parseMoney(parentText);
      const dollarCount = (parentText.match(/\$/g) || []).length;
      const audit = {
        strategy: "text-anchor",
        element: describeEl(parent),
        textNodeText: text.slice(0, 80),
        parentText: parentText.slice(0, 120),
        parsed,
        dollarCount,
        childCount: parent?.childElementCount ?? 0,
        siblingSummary: [],
      };
      if (parent) {
        for (const sib of parent.children) {
          audit.siblingSummary.push({ el: describeEl(sib), text: textOf(sib).slice(0, 60) });
        }
      }
      if (parsed === null && !/\$/.test(parentText)) {
        audit.verdict = "REJECT";
        audit.reason = "pot_label_found_but_parent_has_no_money";
      } else if (dollarCount > 1) {
        audit.verdict = "ACCEPT";
        audit.reason = `matched_first_acceptable_but_parent_text_concatenates_${dollarCount}_amounts (grabbed wrapper not value sibling)`;
      } else {
        audit.verdict = "ACCEPT";
        audit.reason = parsed !== null ? "parseable_from_parent" : "has_dollar_in_parent";
      }
      audits.push(audit);
      candidates.push({ strategy: "text-anchor", text: parentText, node: parent });
    }

    console.log("candidate audits (all):", JSON.stringify(audits, null, 2));
    let selected = null;
    for (const candidate of candidates) {
      const parsed = parseMoney(candidate.text);
      if (parsed !== null || /\$/.test(candidate.text)) {
        selected = { raw: candidate.text, parsed, strategy: candidate.strategy };
        break;
      }
    }
    if (!selected) {
      console.log("selected: null");
      console.log("null_reason: no candidate passed parseMoney or dollar-sign check");
    } else {
      const selAudit = audits.find(
        (a) => a.parentText === selected.raw || a.text === selected.raw
      );
      console.log("selected:", selected);
      if (selAudit?.reason?.includes("concatenates")) {
        console.warn("selection_warning:", selAudit.reason);
      }
    }
    return audits;
  }

  function debugLogHeroCards(root) {
    logQueryCounts("hero hand nodes", ANCHORS.hand, root);
    logQueryCounts("hero data-player-cards", ANCHORS.playerCardsData, root);

    const dataNode = queryFirst(ANCHORS.playerCardsData, root);
    if (dataNode) {
      const imgs = dataNode.querySelectorAll('[role="img"], [data-card], [class*="card"]');
      console.log(`data-player-cards node: ${describeEl(dataNode)}, inner card elements: ${imgs.length}`);
    } else {
      console.log("data-player-cards: not found (queryFirst returned null)");
    }

    const handNodes = queryAll(ANCHORS.hand, root);
    console.log(`hand nodes after queryAll: ${handNodes.length}`);
    console.log(
      "note: queryAll stops at first selector with matches — per-selector counts are in queries group above"
    );

    const imgSelector = '[class*="front"] > div[role="img"], div[role="img"]';
    const handAudits = [];
    for (let i = 0; i < handNodes.length; i++) {
      const hand = handNodes[i];
      const audit = {
        index: i,
        element: describeEl(hand),
        className: String(hand.className || "").slice(0, 80),
      };

      if (hand.closest('[class*="communityCards"]')) {
        audit.verdict = "REJECT";
        audit.reason = "inside_communityCards_container";
        handAudits.push(audit);
        continue;
      }

      const imgs = hand.querySelectorAll(imgSelector);
      audit.imgCount = imgs.length;
      audit.imgQuery = imgSelector;
      audit.imgDetails = [];

      if (imgs.length === 0) {
        audit.verdict = "REJECT";
        audit.reason = "no_role_img_elements_in_hand";
        handAudits.push(audit);
        continue;
      }

      let accepted = 0;
      for (let j = 0; j < imgs.length; j++) {
        const img = imgs[j];
        const detail = { index: j, element: describeEl(img), aria: img.getAttribute("aria-label") || "" };
        if (!isFaceUpCard(img)) {
          detail.verdict = "REJECT";
          detail.reason = detail.aria === "card face down" ? "face_down" : "face_down_or_missing_aria";
        } else {
          const card = cardFromElement(img);
          if (card) {
            detail.verdict = "ACCEPT";
            detail.card = card;
            accepted++;
          } else {
            detail.verdict = "REJECT";
            detail.reason = debugCardRejection(img);
          }
        }
        audit.imgDetails.push(detail);
      }

      if (accepted === 0) {
        audit.verdict = "REJECT";
        audit.reason = "all_imgs_failed_face_up_or_card_parse";
      } else {
        audit.verdict = "ACCEPT";
        audit.reason = `${accepted} face-up card(s) parsed`;
      }
      handAudits.push(audit);
    }

    console.log("hand node audits:", JSON.stringify(handAudits, null, 2));
    const result = extractHeroCards(root);
    if (result.cards.length === 0) {
      console.log("null_reason: no cards after extraction — see hand node audits above");
    }
    return handAudits;
  }

  function debugLogBoardCards(root) {
    logQueryCounts("board data-board-cards", ANCHORS.boardCardsData, root);
    logQueryCounts("board communityCards", ANCHORS.community, root);

    const imgSelector = '[class*="front"] > div[role="img"], div[role="img"]';
    const rootImgCount = root.querySelectorAll(imgSelector).length;
    console.log(`root-level "${imgSelector}" raw count=${rootImgCount} (before any filter)`);

    for (const selector of ANCHORS.boardCardsData) {
      const nodes = root.querySelectorAll(selector);
      console.log(`[data path] "${selector}" raw count=${nodes.length}`);
    }

    const communityNodes = [];
    for (const selector of ANCHORS.community) {
      const nodes = Array.from(root.querySelectorAll(selector));
      console.log(`[community path] "${selector}" raw count=${nodes.length} (before any filter)`);
      communityNodes.push(...nodes);
    }

    if (communityNodes.length === 0) {
      console.log("null_reason: communityCards selector returned 0 nodes — board cannot be read");
    }

    const communityAudits = [];
    for (let i = 0; i < communityNodes.length; i++) {
      const community = communityNodes[i];
      const imgs = community.querySelectorAll('[class*="front"] > div[role="img"], div[role="img"]');
      const audit = {
        index: i,
        element: describeEl(community),
        imgCountBeforeFilter: imgs.length,
        imgDetails: [],
      };
      for (let j = 0; j < imgs.length; j++) {
        const img = imgs[j];
        const detail = { index: j, element: describeEl(img), aria: img.getAttribute("aria-label") || "" };
        if (!isFaceUpCard(img)) {
          detail.verdict = "REJECT";
          detail.reason = "face_down";
        } else {
          const card = cardFromElement(img);
          if (card) {
            detail.verdict = "ACCEPT";
            detail.card = card;
          } else {
            detail.verdict = "REJECT";
            detail.reason = debugCardRejection(img);
          }
        }
        audit.imgDetails.push(detail);
      }
      communityAudits.push(audit);
    }
    console.log("community node audits:", JSON.stringify(communityAudits, null, 2));

    const result = extractBoardCards(root);
    if (result.cards.length === 0) {
      console.log("null_reason: no board cards extracted — check raw query counts and img audits above");
    }
    return communityAudits;
  }

  function debugLogHeroStack(root) {
    logQueryCounts("hero stack: hand (for zone)", ANCHORS.hand, root);
    logQueryCounts("hero stack: yourTurn", ANCHORS.yourTurn, root);
    logQueryCounts("hero stack: heroSeat", ANCHORS.heroSeat, root);

    const handNodes = queryAll(ANCHORS.hand, root);
    console.log(`findHeroZone: scanning ${handNodes.length} hand node(s)`);

    const zoneAudits = [];
    for (let i = 0; i < handNodes.length; i++) {
      const hand = handNodes[i];
      const audit = { index: i, element: describeEl(hand) };
      if (hand.closest('[class*="communityCards"]')) {
        audit.verdict = "SKIP";
        audit.reason = "inside_communityCards";
        zoneAudits.push(audit);
        continue;
      }
      const faceUp = hand.querySelector('[class*="front"] > div[role="img"]:not([aria-label="card face down"])');
      if (!faceUp) {
        audit.verdict = "SKIP";
        audit.reason = "no_face_up_card_in_hand";
        zoneAudits.push(audit);
        continue;
      }
      const zone =
        hand.closest('[id^="player-"]') ||
        hand.closest('[class*="playerWrapper"]') ||
        hand.closest('[class*="opponent"]') ||
        hand.parentElement;
      audit.verdict = "ZONE_FOUND";
      audit.zone = describeEl(zone);
      zoneAudits.push(audit);
    }
    console.log("hero zone search audits:", zoneAudits);

    const yourTurn = queryFirst(ANCHORS.yourTurn, root);
    console.log(`yourTurn queryFirst: ${yourTurn ? describeEl(yourTurn) : "null"}`);

    const heroZone = findHeroZone(root);
    if (!heroZone) {
      console.log("null_reason: findHeroZone returned null — no hand with face-up card and no yourTurn fallback");
      return;
    }
    console.log(`heroZone resolved: ${describeEl(heroZone)}`);

    const moneyEls = heroZone.querySelectorAll("span, div, p");
    console.log(`heroZone query "span, div, p" raw count=${moneyEls.length} (before $ filter)`);

    const moneyAudits = [];
    for (const el of moneyEls) {
      const text = textOf(el);
      const audit = { element: describeEl(el), text: text.slice(0, 60) };
      if (!text) {
        audit.verdict = "REJECT";
        audit.reason = "empty_text";
      } else if (!/\$/.test(text)) {
        audit.verdict = "REJECT";
        audit.reason = "no_dollar_sign";
      } else if (/\bPOT\b/i.test(text)) {
        audit.verdict = "REJECT";
        audit.reason = "contains_POT_label";
      } else {
        audit.verdict = "ACCEPT";
        audit.parsed = parseMoney(text);
      }
      moneyAudits.push(audit);
    }
    console.log("money element audits:", JSON.stringify(moneyAudits, null, 2));

    const accepted = moneyAudits.filter((a) => a.verdict === "ACCEPT");
    if (accepted.length === 0) {
      console.log("null_reason: no span/div/p in heroZone passed $ filter (see money element audits)");
    }
  }

  function debugLogActionSlots(root) {
    const yourTurn = queryFirst(ANCHORS.yourTurn, root);
    const scopes = [];
    const scopeMeta = [];

    if (yourTurn) {
      const scope = yourTurn.closest('[class*="controls"]') || yourTurn.parentElement || yourTurn;
      scopes.push(scope);
      scopeMeta.push({ source: "yourTurn", element: describeEl(scope) });
    }
    const controlsScope = queryFirst(ANCHORS.controls, root);
    scopes.push(controlsScope);
    scopeMeta.push({ source: "controls_anchor", element: describeEl(controlsScope) });
    scopes.push(root);
    scopeMeta.push({ source: "root", element: describeEl(root) });

    console.log("action slot scopes:", scopeMeta);

    const buttonAudits = [];
    for (let si = 0; si < scopeMeta.length; si++) {
      const scopeInfo = scopeMeta[si];
      const scope = scopes[si];
      if (!scope) {
        console.log(`scope ${scopeInfo.source}: null — skipped`);
        continue;
      }
      const rawButtons = scope.querySelectorAll("button, a, [role='button']");
      console.log(`scope ${scopeInfo.source} (${scopeInfo.element}): raw button count=${rawButtons.length}`);

      for (const el of rawButtons) {
        const text = textOf(el);
        const rect = el.getBoundingClientRect();
        const audit = {
          scope: scopeInfo.source,
          element: describeEl(el),
          text: text.slice(0, 80),
          disabled: el.disabled || el.getAttribute("aria-disabled") === "true",
          rect: { left: Math.round(rect.left), top: Math.round(rect.top), w: Math.round(rect.width), h: Math.round(rect.height) },
        };
        if (audit.disabled) {
          audit.verdict = "REJECT";
          audit.reason = "disabled";
        } else if (!text) {
          audit.verdict = "REJECT";
          audit.reason = "empty_text";
        } else if (!/\b(fold|check|call|raise|bet|show cards|sit out|leave)\b/i.test(text)) {
          audit.verdict = "REJECT";
          audit.reason = "no_poker_keyword_match";
        } else if (rect.width < 20 || rect.height < 10) {
          audit.verdict = "REJECT";
          audit.reason = `rect_too_small(${Math.round(rect.width)}x${Math.round(rect.height)})`;
        } else {
          audit.verdict = "ACCEPT";
        }
        buttonAudits.push(audit);
      }
    }

    console.log("button audits (all scopes):", JSON.stringify(buttonAudits, null, 2));

    const result = extractActionSlots(root);
    console.log("deduped buttons (extractActionButtons result):", JSON.stringify(
      result.buttons.map((b) => ({ text: b.text, left: Math.round(b.left), top: Math.round(b.top) })),
      null,
      2
    ));
    console.log("assigned slots:", JSON.stringify(result.slots, null, 2));
    console.log("classified labels:", JSON.stringify(result.labels, null, 2));
    console.log("source:", result.source);

    if (!result.buttons.length) {
      console.log("null_reason: no buttons passed disabled/keyword/rect filters — see button audits");
    }
    return result;
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
      if (DEBUG) debugLogPot(root);
      pot = extractPot(root);
      if (DEBUG) console.log("extract result", { raw: pot.raw, parsed: pot.parsed, source: pot.source });
    });

    logGroup("hero_cards", () => {
      if (DEBUG) debugLogHeroCards(root);
      hero = extractHeroCards(root);
      if (DEBUG) console.log("extract result", { cards: hero.cards, source: hero.source });
    });

    logGroup("board_cards", () => {
      if (DEBUG) debugLogBoardCards(root);
      board = extractBoardCards(root);
      if (DEBUG) console.log("extract result", { cards: board.cards, source: board.source });
    });

    logGroup("hero_stack", () => {
      if (DEBUG) debugLogHeroStack(root);
      stack = extractHeroStack(root);
      if (DEBUG) console.log("extract result", { raw: stack.raw, parsed: stack.parsed, source: stack.source });
    });

    logGroup("action_slots", () => {
      if (DEBUG) {
        actions = debugLogActionSlots(root);
      } else {
        actions = extractActionSlots(root);
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
