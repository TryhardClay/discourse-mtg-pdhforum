// ============================================================
// Mana Symbol Markdown Extension
// Converts {W}, {U}, {B}, {R}, {G}, {C}, {W/U}, etc.
// into Mana font icons using the ms css classes
// ============================================================

const MANA_MAP = {
  "W":    "ms ms-w ms-cost",
  "U":    "ms ms-u ms-cost",
  "B":    "ms ms-b ms-cost",
  "R":    "ms ms-r ms-cost",
  "G":    "ms ms-g ms-cost",
  "C":    "ms ms-c ms-cost",
  "W/U":  "ms ms-wu ms-cost ms-split",
  "W/B":  "ms ms-wb ms-cost ms-split",
  "U/B":  "ms ms-ub ms-cost ms-split",
  "U/R":  "ms ms-ur ms-cost ms-split",
  "B/R":  "ms ms-br ms-cost ms-split",
  "B/G":  "ms ms-bg ms-cost ms-split",
  "R/G":  "ms ms-rg ms-cost ms-split",
  "R/W":  "ms ms-rw ms-cost ms-split",
  "G/W":  "ms ms-gw ms-cost ms-split",
  "G/U":  "ms ms-gu ms-cost ms-split",
  "2/W":  "ms ms-2w ms-cost ms-split",
  "2/U":  "ms ms-2u ms-cost ms-split",
  "2/B":  "ms ms-2b ms-cost ms-split",
  "2/R":  "ms ms-2r ms-cost ms-split",
  "2/G":  "ms ms-2g ms-cost ms-split",
  "X":    "ms ms-x ms-cost",
  "T":    "ms ms-tap",
  "Q":    "ms ms-untap",
  "S":    "ms ms-s ms-cost",
  "0":    "ms ms-0 ms-cost",
  "1":    "ms ms-1 ms-cost",
  "2":    "ms ms-2 ms-cost",
  "3":    "ms ms-3 ms-cost",
  "4":    "ms ms-4 ms-cost",
  "5":    "ms ms-5 ms-cost",
  "6":    "ms ms-6 ms-cost",
  "7":    "ms ms-7 ms-cost",
  "8":    "ms ms-8 ms-cost",
  "9":    "ms ms-9 ms-cost",
  "10":   "ms ms-10 ms-cost",
  "11":   "ms ms-11 ms-cost",
  "12":   "ms ms-12 ms-cost",
  "13":   "ms ms-13 ms-cost",
  "14":   "ms ms-14 ms-cost",
  "15":   "ms ms-15 ms-cost",
  "16":   "ms ms-16 ms-cost",
  "20":   "ms ms-20 ms-cost",
};

// Regex: matches {W}, {W/U}, {10}, {T} etc.
const MANA_REGEX = /\{([WUBRGCTQSXwubrgctqsx]|[0-9]+|[WUBRG2]\/[WUBRG])\}/g;

function manaMatcher(state, silent) {
  const src = state.src;
  const pos = state.pos;

  if (src.charCodeAt(pos) !== 0x7B /* { */) return false;

  MANA_REGEX.lastIndex = pos;
  const match = MANA_REGEX.exec(src);

  if (!match || match.index !== pos) return false;

  const symbol = match[1].toUpperCase();
  const cssClass = MANA_MAP[symbol];

  if (!cssClass) return false;

  if (!silent) {
    const token = state.push("mana_symbol", "", 0);
    token.attrSet("class", cssClass);
    token.content = symbol;
    token.markup = match[0];
  }

  state.pos += match[0].length;
  return true;
}

function manaRenderer(tokens, idx) {
  const token = tokens[idx];
  const cssClass = token.attrGet("class") || "";
  const symbol = token.content;
  return `<span class="mana-symbol" title="{${symbol}}"><i class="${cssClass}"></i></span>`;
}

export function setup(helper) {
  if (!helper.markdownIt) return;

  helper.allowList([
    "span.mana-symbol",
    "i.ms",
    "i.ms-w", "i.ms-u", "i.ms-b", "i.ms-r", "i.ms-g", "i.ms-c",
    "i.ms-cost", "i.ms-split", "i.ms-tap", "i.ms-untap",
    "i.ms-wu", "i.ms-wb", "i.ms-ub", "i.ms-ur", "i.ms-br",
    "i.ms-bg", "i.ms-rg", "i.ms-rw", "i.ms-gw", "i.ms-gu",
    "i.ms-x", "i.ms-s",
    "i.ms-0", "i.ms-1", "i.ms-2", "i.ms-3", "i.ms-4", "i.ms-5",
    "i.ms-6", "i.ms-7", "i.ms-8", "i.ms-9", "i.ms-10",
    "i.ms-11", "i.ms-12", "i.ms-13", "i.ms-14", "i.ms-15",
    "i.ms-16", "i.ms-20",
    "i.ms-2w", "i.ms-2u", "i.ms-2b", "i.ms-2r", "i.ms-2g",
  ]);

  helper.registerPlugin((md) => {
    md.inline.ruler.push("mana_symbols", manaMatcher);
    md.renderer.rules["mana_symbol"] = manaRenderer;
  });
}
