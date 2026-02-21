// ============================================================
// MTG Card Tooltip Markdown Extension
// Converts [[Card Name]] into a hoverable link that shows
// the card image fetched from the Scryfall API
// ============================================================

const CARD_REGEX = /\[\[([^\]]+)\]\]/;

function cardMatcher(state, silent) {
  const src = state.src;
  const pos = state.pos;

  // Must start with [[
  if (src.charCodeAt(pos) !== 0x5B || src.charCodeAt(pos + 1) !== 0x5B) {
    return false;
  }

  const match = src.slice(pos).match(CARD_REGEX);
  if (!match) return false;

  const cardName = match[1].trim();
  if (!cardName) return false;

  if (!silent) {
    const token = state.push("mtg_card", "", 0);
    token.content = cardName;
    token.markup = match[0];
  }

  state.pos += match[0].length;
  return true;
}

function cardRenderer(tokens, idx) {
  const cardName = tokens[idx].content;
  const encodedName = encodeURIComponent(cardName);
  const scryfallUrl = `https://api.scryfall.com/cards/named?fuzzy=${encodedName}&format=image&version=normal`;
  const scryfallPage = `https://scryfall.com/search?q=${encodedName}`;

  return `<a class="mtg-card-link" href="${scryfallPage}" target="_blank" rel="noopener" data-card="${encodedName}">${cardName}<span class="mtg-card-tooltip"><img src="${scryfallUrl}" alt="${cardName}" loading="lazy" /></span></a>`;
}

export function setup(helper) {
  if (!helper.markdownIt) return;

  helper.allowList([
    "a.mtg-card-link",
    "span.mtg-card-tooltip",
    "img[loading]",
    "img[alt]",
  ]);

  helper.registerPlugin((md) => {
    md.inline.ruler.push("mtg_cards", cardMatcher);
    md.renderer.rules["mtg_card"] = cardRenderer;
  });
}
