/**
 * Per-dish icons.
 *
 * The glyph a dish used to wear was the *restaurant's* — a cafe's whole menu came
 * out as a row of coffee cups, and an ice cream, a brownie and a waffle were
 * indistinguishable from one another. A menu is a list of different things, so
 * each dish gets an icon for what the dish actually is.
 *
 * The tile around the icon still comes from the venue's theme, so the page keeps
 * its identity: this swaps the shape, never the colour or the pattern.
 *
 * Classification is by dish name and tags, and the rule is that a name's head
 * noun wins: "Cold Brew Tiramisu" is a dessert, not a coffee. It is a lookup,
 * not a model: a dish nobody has a rule for falls back to a plate, which is
 * honest rather than a confident wrong guess.
 */

// Ordered longest-first at match time; the array order here is only for reading.
const DISH_RULES = [
  ["coffee", ["filter coffee", "cold brew", "espresso", "cappuccino", "latte", "macchiato", "americano", "pour over", "flat white", "cortado", "mocha", "coffee"]],
  ["tiffin", ["masala dosa", "ghee roast dosa", "rava idli", "idli sambar", "podi idli", "medu vada", "kesari bath", "idiyappam", "pundi", "uttapam", "dosa", "idli", "vada", "appam", "undhiyu", "uppma", "upma", "tiffin"]],
  ["rice", ["biryani", "pulao", "khichdi", "pulihora", "pongal", "bisi bele bath", "chawal", "rice"]],
  ["curry", ["butter chicken", "paneer butter masala", "dal makhani", "chicken curry", "mutton curry", "korma", "vindaloo", "rogan josh", "kadhai", "curry", "masala", "dal", "sambar", "rasam"]],
  ["flatbread", ["butter naan", "tandoori roti", "garlic naan", "chapati", "roti", "paratha", "naan", "phulka", "bhatura", "poori"]],
  ["kebab", ["paneer tikka", "leg of lamb", "tandoori", "kebab", "tikka", "seekh", "chaat", "pani puri"]],
  ["pizza", ["margherita pizza", "four cheese pizza", "wood fired pizza", "wood fired margherita", "margherita", "pizza"]],
  ["pasta", ["arrabbiata pasta", "pasta al pomodoro", "alfredo pasta", "lasagna", "spaghetti", "penne", "pasta", "risotto", "macaroni"]],
  ["burger", ["crispy chicken sliders", "grilled cheese sandwich", "chicken burger", "veggie burger", "chicken puff", "egg puff", "slider", "burger", "sandwich", "wrap", "bun", "toast", "puff", "bruschetta"]],
  ["dessert", ["chocolate brownie", "brownie with ice cream", "belgian waffles", "missing angle", "mud pie", "apple pie", "banana walnut loaf", "butter croissant", "vanilla cupcake", "gulab jamun", "payasam", "khar badam", "mysore pak", "tiramisu", "cupcake", "brownie", "waffle", "pie", "pastry", "croissant", "cookie", "cake", "loaf", "scone", "pudding", "cheesecake"]],
  ["icecream", ["frozen custard", "kulfi falooda", "ice cream", "icecream", "sorbet", "gelato", "kulfi", "falooda"]],
  ["drink", ["craft lager", "stout", "juice", "smoothie", "lassi", "shandy", "beer", "lager", "milkshake"]],
  ["curryleaf", ["gasa gase", "gulab jamun", "payasam"]],
  ["fry", ["loaded fries", "fries", "pakora", "bhaji", "fritter", "chips"]],
  ["momo", ["momo", "dumpling", "spring roll", "dim sum", "gyoza", "wonton"]],
  ["thali", ["andhra meals", "thali", "tiffin meal", "combo meal", "meals"]],
  ["sushi", ["sushi", "sashimi", "maki", "ramen", "tempura"]],
  ["chaat", ["pani puri", "bhel puri", "chaat", "samosa", "pakora"]],
  ["plate", []],
];

/**
 * Choose an icon key for a dish.
 *
 * The rule is **the last match wins**, which is a head-noun heuristic, and it
 * beats "longest phrase wins" on the cases that actually come up:
 *
 *   "Cold Brew Tiramisu"  -> tiramisu  (a plated dessert), not "cold brew"
 *   "Chocolate Brownie"    -> brownie
 *   "Masala Dosa"          -> dosa
 *
 * Taking the longest phrase instead gets Cold Brew Tiramisu wrong, because
 * "cold brew" is nine characters and "tiramisu" is eight. Length measures how
 * specific a phrase is; position measures what the dish *is*, and a reader
 * looking at "Cold Brew Tiramisu" is looking at a tiramisu.
 *
 * `name` is searched before `tags`, because a name is what the reader is
 * reading. Tags are a fallback, and they are what rescues a name that says
 * nothing at all: Corner House's "Missing Angle" is only placeable because its
 * tags say dessert.
 */
export function dishIconKey(name, tags) {
  const bestIn = (haystack) => {
    let best = null;
    for (const [key, phrases] of DISH_RULES) {
      for (const phrase of phrases) {
        const at = haystack.indexOf(phrase);
        if (at === -1) continue;
        // Later position wins; a longer phrase at the same position wins.
        if (!best || at > best.at || (at === best.at && phrase.length > best.length)) {
          best = { key, at, length: phrase.length };
        }
      }
    }
    return best;
  };

  const fromName = bestIn((name || "").toLowerCase());
  if (fromName) return fromName.key;

  const fromTags = bestIn((tags || "").toLowerCase());
  return fromTags ? fromTags.key : "plate";
}

// ---------------------------------------------------------------------------
// Shapes. Drawn in the same 64x64 space as foodIcons.jsx so they drop straight
// into the existing tile.
// ---------------------------------------------------------------------------

export const DISH_ICON_PATHS = {
  coffee: `
    <path d="M17 26h27v15c0 7-6 12-13 12h-1c-7 0-13-5-13-12V26Z" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M44 30h4c6 0 6 11 0 11h-4" fill="none" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M24 19c-4-5 4-7 0-12M33 19c-4-5 4-7 0-12" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
    <path d="M21 47h20" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
  `,
  tiffin: `
    <path d="M13 42c0-14 9-25 21-25s21 11 21 25c0 6-9 10-21 10s-21-4-21-10Z" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M18 41c8 4 20 4 28 0" fill="none" stroke="#FF6B35" stroke-width="3" stroke-linecap="round"/>
    <circle cx="26" cy="32" r="3" fill="#C6F135" stroke="#2A0E1E" stroke-width="2"/>
    <circle cx="38" cy="35" r="3" fill="#E63946" stroke="#2A0E1E" stroke-width="2"/>
  `,
  rice: `
    <path d="M12 34h40c0 11-9 18-20 18s-20-7-20-18Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <path d="M9 33h46" stroke="#2A0E1E" stroke-width="4" stroke-linecap="round"/>
    <circle cx="25" cy="27" r="2.5" fill="#C6F135" stroke="#2A0E1E" stroke-width="1.5"/>
    <circle cx="35" cy="25" r="2.5" fill="#FF6B35" stroke="#2A0E1E" stroke-width="1.5"/>
    <circle cx="42" cy="29" r="2" fill="#E63946" stroke="#2A0E1E" stroke-width="1.5"/>
  `,
  curry: `
    <path d="M11 33h42c0 12-9 20-21 20s-21-8-21-20Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <path d="M8 32h48" stroke="#2A0E1E" stroke-width="4" stroke-linecap="round"/>
    <path d="M24 24c-4-5 4-7 0-12M34 24c-4-5 4-7 0-12" fill="none" stroke="#FF6B35" stroke-width="3" stroke-linecap="round"/>
    <circle cx="32" cy="41" r="3" fill="#C6F135" stroke="#2A0E1E" stroke-width="1.5"/>
  `,
  flatbread: `
    <ellipse cx="32" cy="34" rx="20" ry="13" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <circle cx="26" cy="31" r="2.5" fill="#C6F135" stroke="#2A0E1E" stroke-width="1.5"/>
    <circle cx="37" cy="36" r="2.5" fill="#E63946" stroke="#2A0E1E" stroke-width="1.5"/>
    <circle cx="36" cy="28" r="2" fill="#FF6B35" stroke="#2A0E1E" stroke-width="1.5"/>
    <path d="M18 48h28" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
  `,
  kebab: `
    <path d="M14 44c0-10 8-16 18-16s18 6 18 16" fill="none" stroke="#2A0E1E" stroke-width="4" stroke-linecap="round"/>
    <rect x="20" y="24" width="24" height="14" rx="4" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M26 38v10M38 38v10" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
    <circle cx="27" cy="31" r="2.5" fill="#C6F135" stroke="#2A0E1E" stroke-width="1.5"/>
    <circle cx="37" cy="31" r="2.5" fill="#FF6B35" stroke="#2A0E1E" stroke-width="1.5"/>
  `,
  pizza: `
    <path d="M32 8c13 9 21 18 21 27 0 8-9 13-21 13s-21-5-21-13c0-9 8-18 21-27Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <circle cx="27" cy="36" r="3.5" fill="#E63946" stroke="#2A0E1E" stroke-width="1.5"/>
    <circle cx="38" cy="30" r="3" fill="#C6F135" stroke="#2A0E1E" stroke-width="1.5"/>
    <circle cx="34" cy="42" r="3" fill="#FF6B35" stroke="#2A0E1E" stroke-width="1.5"/>
  `,
  pasta: `
    <ellipse cx="32" cy="42" rx="21" ry="8" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M17 40c2-14 8-24 15-24s13 10 15 24" fill="none" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
    <path d="M24 26c4 3 12 3 16 0" fill="none" stroke="#FF6B35" stroke-width="3" stroke-linecap="round"/>
    <path d="M26 36c4 2 8 2 12 0" fill="none" stroke="#C6F135" stroke-width="3" stroke-linecap="round"/>
  `,
  burger: `
    <path d="M14 30c0-8 8-13 18-13s18 5 18 13H14Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <path d="M12 33h40c0 3-3 5-7 5H19c-4 0-7-2-7-5Z" fill="#C6F135" stroke="#2A0E1E" stroke-width="2.5"/>
    <path d="M15 41h34c0 4-3 6-7 6H22c-4 0-7-2-7-6Z" fill="#FF6B35" stroke="#2A0E1E" stroke-width="2.5"/>
    <path d="M18 48h28" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
  `,
  dessert: `
    <path d="M18 46h28l-4-16H22l-4 16Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <path d="M20 30c4 3 20 3 24 0" fill="none" stroke="#E63946" stroke-width="3" stroke-linecap="round"/>
    <circle cx="32" cy="18" r="6" fill="#C6F135" stroke="#2A0E1E" stroke-width="2.5"/>
    <path d="M32 24v-4" stroke="#2A0E1E" stroke-width="2" stroke-linecap="round"/>
  `,
  icecream: `
    <path d="M22 30h20L32 54 22 30Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <circle cx="25" cy="24" r="8" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <circle cx="39" cy="24" r="8" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <circle cx="32" cy="15" r="8" fill="#FF6B35" stroke="#2A0E1E" stroke-width="3"/>
  `,
  drink: `
    <path d="M22 16h20l-3 34c0 3-3 5-7 5s-7-2-7-5l-3-34Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <path d="M24 32h16" stroke="#C6F135" stroke-width="4" stroke-linecap="round"/>
    <path d="M38 14l6-6" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
  `,
  curryleaf: `
    <path d="M18 46c-2-16 8-30 28-32-2 20-14 30-28 32Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <path d="M20 45c6-11 14-19 24-26" fill="none" stroke="#2A0E1E" stroke-width="2.5" stroke-linecap="round"/>
    <circle cx="30" cy="28" r="2.5" fill="#C6F135" stroke="#2A0E1E" stroke-width="1.5"/>
  `,
  fry: `
    <path d="M20 22h24l-3 30H23l-3-30Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <path d="M24 16l2-8M32 16V6M40 16l-2-8" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
    <path d="M26 34h12" stroke="#FF6B35" stroke-width="3" stroke-linecap="round"/>
  `,
  momo: `
    <path d="M32 14c11 0 19 9 19 19 0 9-8 15-19 15s-19-6-19-15c0-10 8-19 19-19Z" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M18 33c8 5 20 5 28 0" fill="none" stroke="#2A0E1E" stroke-width="2.5" stroke-linecap="round"/>
    <path d="M25 24c4 4 10 4 14 0" fill="none" stroke="#C6F135" stroke-width="3" stroke-linecap="round"/>
  `,
  thali: `
    <circle cx="32" cy="33" r="20" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <circle cx="32" cy="33" r="8" fill="none" stroke="#2A0E1E" stroke-width="2.5"/>
    <circle cx="32" cy="17" r="4" fill="#FF6B35" stroke="#2A0E1E" stroke-width="2"/>
    <circle cx="18" cy="40" r="4" fill="#C6F135" stroke="#2A0E1E" stroke-width="2"/>
    <circle cx="46" cy="40" r="4" fill="#E63946" stroke="#2A0E1E" stroke-width="2"/>
  `,
  sushi: `
    <ellipse cx="24" cy="38" rx="12" ry="9" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <ellipse cx="42" cy="30" rx="10" ry="8" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <circle cx="24" cy="38" r="3" fill="#E63946" stroke="#2A0E1E" stroke-width="1.5"/>
    <circle cx="42" cy="30" r="2.5" fill="#C6F135" stroke="#2A0E1E" stroke-width="1.5"/>
    <path d="M14 50h36" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
  `,
  chaat: `
    <path d="M14 32h36c0 12-8 20-18 20s-18-8-18-20Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <circle cx="26" cy="30" r="3" fill="#FF6B35" stroke="#2A0E1E" stroke-width="1.5"/>
    <circle cx="36" cy="33" r="3" fill="#C6F135" stroke="#2A0E1E" stroke-width="1.5"/>
    <circle cx="31" cy="26" r="2.5" fill="#E63946" stroke="#2A0E1E" stroke-width="1.5"/>
    <path d="M40 18c4 4 6 8 6 12" fill="none" stroke="#2A0E1E" stroke-width="2" stroke-linecap="round" stroke-dasharray="3 3"/>
  `,
  plate: `
    <circle cx="32" cy="34" r="19" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <circle cx="32" cy="34" r="10" fill="none" stroke="#2A0E1E" stroke-width="2" stroke-dasharray="3 4"/>
    <path d="M14 52h36" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
  `,
};

export function dishIconMarkup(dish) {
  const key = dishIconKey(dish?.name, dish?.tags);
  return DISH_ICON_PATHS[key] || DISH_ICON_PATHS.plate;
}
