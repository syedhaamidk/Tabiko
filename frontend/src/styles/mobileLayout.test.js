/**
 * Narrow-screen rules that cannot be eyeballed in jsdom.
 *
 * jsdom matches no media queries and resolves no cascade, so a responsive
 * regression passes every component test while breaking every phone. These
 * parse the real global.css the way fontTokens.test.js does and assert the
 * rules that were each added to fix a photographed bug:
 *
 *   - hero stats stretch full-width on phones (ragged pills),
 *   - the Google sign-in stacks divider-over-button on phones (a fixed
 *     280px iframe next to its divider overflows a ~320px row),
 *   - the card flavor sticker hides on phones (it covered names' first
 *     letters, measured on a real rendered card).
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const CSS_PATH = resolve(HERE, "global.css");

const css = readFileSync(CSS_PATH, "utf8");

/** The body of the max-width:620px block, brace-matched. */
function mobileBlock() {
  const start = css.indexOf("@media (max-width: 620px)");
  expect(start, "the 620px media query is gone").toBeGreaterThan(-1);
  let depth = 0;
  let end = -1;
  for (let i = css.indexOf("{", start); i < css.length; i += 1) {
    if (css[i] === "{") depth += 1;
    if (css[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  expect(end, "the 620px block never closes").toBeGreaterThan(start);
  return css.slice(start, end);
}

/** Declarations of one selector inside a block, or null. */
function declarations(block, selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = block.match(new RegExp(`${escaped}\\s*\\{([^}]*)\\}`));
  return match ? match[1] : null;
}

describe("narrow-screen rules", () => {
  const mobile = mobileBlock();

  it("stretches the hero stats full-width", () => {
    const rules = declarations(mobile, ".hero-copy__stats");
    expect(rules, ".hero-copy__stats missing from the 620px block").toBeTruthy();
    expect(rules).toContain("justify-content: stretch");
  });

  it("stacks the Google sign-in instead of overflowing the card", () => {
    const rules = declarations(mobile, ".google-signin--inline");
    expect(
      rules,
      ".google-signin--inline missing from the 620px block",
    ).toBeTruthy();
    expect(rules).toContain("flex-direction: column");
  });

  it("hides the card flavor sticker that covers names", () => {
    // Doubled specificity on purpose: the base rule below wins ties on
    // source order, so a flat selector here would silently do nothing.
    const rules = declarations(mobile, ".restaurant-card .restaurant-card__flavor-sticker");
    expect(
      rules,
      "the sticker rule is missing from the 620px block",
    ).toBeTruthy();
    expect(rules).toContain("display: none");
  });
});
