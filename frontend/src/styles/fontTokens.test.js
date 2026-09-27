/**
 * Display and body fonts reach the page through the theme, not through a literal.
 *
 * Twenty-one `font-family: "Bungee", cursive` declarations and eight
 * `font-family: "Fredoka", sans-serif` ones used to sit in global.css as plain
 * strings. They looked right, they were not wrong on any single page, and they
 * silently ignored every theme: a `fine_dine` place would set
 * `--font-display` to Bodoni Moda, the page heading would change, and a dish name
 * 40 lines further down would still be Bungee. That is the worst shape of bug --
 * it looks like a design decision, so nobody files it.
 *
 * The point of this file is not that the variable exists. It is that changing a
 * theme's `font_pair` changes what these specific spots render.
 *
 * **jsdom cannot help here.** Its `getComputedStyle` returns the literal string
 * `"var(--font-display)"` rather than resolving it, so a test written the obvious
 * way would assert nothing at all. The resolution below is therefore done by
 * hand, against the real `global.css` and the real `theme_tokens.json` -- which
 * is also why this test cannot drift: if either file changes shape, it fails
 * rather than quietly checking a copy.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const CSS_PATH = resolve(HERE, "global.css");
const TOKENS_PATH = resolve(HERE, "../../../backend/app/themes/theme_tokens.json");
const INDEX_HTML = resolve(HERE, "../../index.html");

const css = readFileSync(CSS_PATH, "utf8");
const tokensFile = readFileSync(TOKENS_PATH, "utf8");

/** Every theme in the backend's real token file, as { id, font_pair }. */
function themes() {
  const parsed = JSON.parse(tokensFile);
  const table = parsed.themes ?? parsed;
  const entries = Array.isArray(table)
    ? table.map((t) => [t.id, t])
    : Object.entries(table);
  return entries.map(([id, t]) => ({ id, fontPair: t.font_pair ?? {} }));
}

const THEMES = themes();

/**
 * The custom properties the page starts with, from `:root`.
 *
 * These are the fallbacks. A theme overwrites them at runtime, which is why they
 * have to be real font names and not something like `inherit`.
 */
function rootCustomProperties() {
  const rootBlock = css.slice(css.indexOf(":root"), css.indexOf("}", css.indexOf(":root")));
  const found = {};
  for (const [, name, value] of rootBlock.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    found[name] = value.trim();
  }
  return found;
}

const ROOT_VARS = rootCustomProperties();

/**
 * Every `font-family` declaration in the sheet, with the selector that owns it.
 *
 * The selector matters: the whole failure was that *particular* rules opted out
 * of the variable, so a test that only counted occurrences of the literal could
 * not say which parts of the page were affected.
 */
function fontFamilyRules() {
  const rules = [];
  // Comments are stripped first so a declaration inside a comment is not counted
  // as a live rule -- which would make the count wrong in the forgiving
  // direction, the direction that hides regressions.
  const stripped = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const blockPattern = /([^{}]+)\{([^{}]*)\}/g;
  for (const [, selector, body] of stripped.matchAll(blockPattern)) {
    const family = body.match(/font-family\s*:\s*([^;]+);/);
    if (family) {
      rules.push({ selector: selector.trim().replace(/\s+/g, " "), value: family[1].trim() });
    }
  }
  return rules;
}

const RULES = fontFamilyRules();

/** Resolve a `var()` chain against a set of custom properties. */
function resolveFontFamily(value, variables) {
  let current = value;
  // Bounded rather than `while (/var()/)`, so a self-referential custom property
  // fails the test instead of hanging it.
  for (let pass = 0; pass < 5; pass += 1) {
    const match = current.match(/^var\((--[\w-]+)\)$/);
    if (!match) return current;
    const replacement = variables[match[1]];
    if (replacement === undefined) return current;
    current = replacement;
  }
  throw new Error(`--font-display does not resolve: ${value} is circular`);
}

/** The custom properties a theme puts on the root, on top of the defaults. */
function variablesFor(theme) {
  return {
    ...ROOT_VARS,
    "--font-display": theme.fontPair.display ?? ROOT_VARS["--font-display"],
    "--font-body": theme.fontPair.body ?? ROOT_VARS["--font-body"],
  };
}

describe("the page has fonts to resolve against", () => {
  it("defines the display and body properties it consumes", () => {
    // If either disappears, every `var()` below falls back to nothing and the
    // browser uses its own default serif -- a page that renders but looks wrong.
    expect(ROOT_VARS["--font-display"]).toBeTruthy();
    expect(ROOT_VARS["--font-body"]).toBeTruthy();
  });

  it("still names Bungee as the pre-theme default", () => {
    // This literal is the fallback, and it is *supposed* to be a literal. It is
    // the one place a font name has to be written out.
    expect(ROOT_VARS["--font-display"]).toContain("Bungee");
  });

  it("found the rules it is here to check", () => {
    // Guards the guard: if the parser stopped matching, every assertion below
    // would pass against an empty list, which is the classic way a test like
    // this rots into a no-op.
    expect(RULES.length).toBeGreaterThan(30);
    expect(RULES.some((rule) => rule.selector.includes("dish-card"))).toBe(true);
  });
});

describe("no themed font is hardcoded", () => {
  const offenders = RULES.filter(
    (rule) => !rule.value.includes("var(") && rule.value !== "inherit",
  );

  it("leaves no display or body font as a literal", () => {
    const described = offenders.map((r) => `${r.selector} { ${r.value} }`);
    expect(described).toEqual([]);
  });

  it("uses the display variable in every rule that asks for a display font", () => {
    // The 21 rules this change is about, named so a regression says which one.
    const expected = [
      ".filter-shell__heading strong",
      ".food-popup__card strong",
      ".dish-card h3",
      ".review-composer__rating label",
      ".review-card__avatar",
      ".review-card__rating",
      ".brand__wordmark",
      ".festival-sticker, .festival-food-sticker, .festival-doodle",
      ".festival-marquee span",
      ".craving-burst",
      ".restaurant-card__poster-number",
      ".good-food-stamp",
      ".detail-hero__burst",
      ".detail-hero__ticker",
      ".select-menu__listhead",
      ".directions-card__title",
      ".directions-card__totals strong",
      ".directions-card__step-distance",
      ".cluster-marker b",
      ".food-map .leaflet-control-zoom a",
      ".map-stamp strong",
    ];
    for (const selector of expected) {
      const rule = RULES.find((candidate) => candidate.selector === selector);
      expect(rule, `no font-family rule found for ${selector}`).toBeTruthy();
      expect(rule.value, `${selector} does not use --font-display`).toBe(
        "var(--font-display)",
      );
    }
    expect(expected).toHaveLength(21);
  });

  it("uses the body variable where the theme's body font belongs", () => {
    // The same bug in the same file, one token over: eight rules read as body
    // text and ignored `font_pair.body`.
    const expected = [
      ".brand__wordmark em",
      ".festival-sticker small",
      ".select-menu__listhead small",
      ".select-menu__search input",
      ".map-road-label span",
      ".map-city-label span",
      ".map-landmark-label span",
      ".map-stamp",
    ];
    for (const selector of expected) {
      const rule = RULES.find((candidate) => candidate.selector === selector);
      expect(rule, `no font-family rule found for ${selector}`).toBeTruthy();
      expect(rule.value, `${selector} does not use --font-body`).toBe("var(--font-body)");
    }
  });
});

describe("changing a theme's font_pair changes what these spots render", () => {
  const DISPLAY_SPOTS = [".dish-card h3", ".review-card__rating", ".map-stamp strong", ".brand__wordmark"];

  it("resolves each display spot to a real theme's font", () => {
    const fineDine = THEMES.find((t) => t.id === "fine_dine");
    expect(fineDine, "the fine_dine theme is missing from theme_tokens.json").toBeTruthy();
    expect(fineDine.fontPair.display).toBeTruthy();

    const variables = variablesFor(fineDine);
    for (const selector of DISPLAY_SPOTS) {
      const rule = RULES.find((candidate) => candidate.selector === selector);
      expect(resolveFontFamily(rule.value, variables), `${selector} on fine_dine`).toBe(
        fineDine.fontPair.display,
      );
    }
  });

  it("gives different fonts to different themes, for the same spot", () => {
    // This is the assertion that the old hardcoded sheet could never satisfy. A
    // dish name has to look different on a fine-dining place and a street-food
    // one; when it did not, nothing was broken enough to be reported.
    const rule = RULES.find((candidate) => candidate.selector === ".dish-card h3");
    const rendered = THEMES.map((theme) => ({
      id: theme.id,
      font: resolveFontFamily(rule.value, variablesFor(theme)),
    }));

    expect(new Set(rendered.map((entry) => entry.font)).size).toBeGreaterThan(1);
    const fineDine = rendered.find((entry) => entry.id === "fine_dine");
    const streetFood = rendered.find((entry) => entry.id === "street_food");
    expect(fineDine.font).not.toBe(streetFood.font);
    expect(streetFood.font).toContain("Bungee");
  });

  it("changes the rendered font when only the font_pair changes", () => {
    // The single-theme version of the same claim, stated as a substitution, so
    // the thing under test is unmistakably "the theme moved and the spot moved
    // with it".
    const rule = RULES.find((candidate) => candidate.selector === ".dish-card h3");
    const before = resolveFontFamily(rule.value, variablesFor({ fontPair: { display: "'Rozha One', serif" } }));
    const after = resolveFontFamily(rule.value, variablesFor({ fontPair: { display: "'Bodoni Moda', serif" } }));

    expect(before).toBe("'Rozha One', serif");
    expect(after).toBe("'Bodoni Moda', serif");
    expect(after).not.toBe(before);
  });

  it("gives every theme a body font too, and the body spots follow it", () => {
    const rule = RULES.find((candidate) => candidate.selector === ".map-stamp");
    for (const theme of THEMES) {
      expect(theme.fontPair.body, `${theme.id} has no body font`).toBeTruthy();
      expect(resolveFontFamily(rule.value, variablesFor(theme))).toBe(
        theme.fontPair.body,
      );
    }
  });
});

describe("a theme can only use a font the page actually loads", () => {
  const indexHtml = readFileSync(INDEX_HTML, "utf8");

  it("loads every font named in a theme's font_pair", () => {
    // A theme can name a font that was never requested, in which case the
    // browser falls back to a default and the theme silently does not apply.
    // The loader is the one place a font name has to be a literal, which is why
    // it is checked against the token file rather than trusted.
    const loader = indexHtml.match(/fonts\.googleapis\.com\/css2\?[^"']+/)?.[0] ?? "";
    expect(loader, "the Google Fonts loader is missing from index.html").toBeTruthy();

    const missing = [];
    for (const theme of THEMES) {
      for (const value of [theme.fontPair.display, theme.fontPair.body]) {
        if (!value) continue;
        // "'Noto Serif SC', serif" -> "Noto+Serif+SC"
        const family = value.split(",")[0].trim().replace(/^['"]|['"]$/g, "");
        const encoded = family.replace(/ /g, "+");
        if (!loader.includes(encoded)) missing.push(`${theme.id}: ${family}`);
      }
    }
    expect(missing).toEqual([]);
  });
});
