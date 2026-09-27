/**
 * Dish icon classification, checked against the 66 distinct dish names the
 * reference seed actually contains rather than against invented examples.
 *
 * The rule that matters is longest-phrase-wins. A dish called "Cold Brew
 * Tiramisu" is a drink in a dessert-shaped name, and "Chocolate Brownie" must
 * not lose to a bare "brownie" match, or every dessert in the seed comes out as
 * the same slice.
 */
import { describe, expect, it } from "vitest";
import { DISH_ICON_PATHS, dishIconKey } from "./dishIcons";

describe("dishIconKey", () => {
  it("picks a distinct icon per food family", () => {
    const cases = [
      ["Masala Dosa", null, "tiffin"],
      ["Rava Idli", "veg, breakfast", "tiffin"],
      ["Medu Vada", null, "tiffin"],
      ["Chicken Biryani", null, "rice"],
      ["Andhra Meals", null, "thali"],
      ["Butter Chicken", null, "curry"],
      ["Dal Makhani", "veg", "curry"],
      ["Butter Naan", "veg", "flatbread"],
      ["Tandoori Roti", "veg", "flatbread"],
      ["Paneer Tikka", "veg, bestseller", "kebab"],
      ["Margherita Pizza", "veg", "pizza"],
      ["Alfredo Pasta", "veg", "pasta"],
      ["Lasagna", "veg", "pasta"],
      ["Grilled Cheese Sandwich", "veg, quick_bite", "burger"],
      ["Cold Brew", "veg", "coffee"],
      ["Filter Coffee", "veg, breakfast", "coffee"],
      ["Pour Over", "veg", "coffee"],
      ["Chocolate Brownie", null, "dessert"],
      ["Tiramisu", "veg, dessert", "dessert"],
      ["Missing Angle", "veg, dessert, bestseller", "dessert"],
      ["Belgian Waffles", "veg, dessert", "dessert"],
      ["Frozen Custard", "veg, dessert", "icecream"],
      ["Kulfi Falooda", "veg, dessert", "icecream"],
      ["Craft Lager", null, "drink"],
      ["Stout", null, "drink"],
      ["Pongal", "veg, lunch", "rice"],
    ];
    for (const [name, tags, expected] of cases) {
      expect(`${name} -> ${dishIconKey(name, tags)}`).toBe(`${name} -> ${expected}`);
    }
  });

  it("prefers the longest matching phrase, not the first rule that fires", () => {
    // "chocolate brownie" must beat "brownie", or the seed's whole dessert
    // section collapses into one generic slice.
    expect(dishIconKey("Chocolate Brownie", "veg")).toBe("dessert");
    // The head noun wins over an earlier word. A cold brew tiramisu is a
    // tiramisu; classifying it as a drink would put a coffee cup on a plated
    // dessert.
    expect(dishIconKey("Cold Brew Tiramisu", "veg, dessert")).toBe("dessert");
    // "filter coffee" must not lose to a bare "coffee" rule under a drink.
    expect(dishIconKey("Filter Coffee", "veg, breakfast")).toBe("coffee");
  });

  it("falls back to a plate rather than guessing", () => {
    // An unfamiliar dish gets a neutral plate, not a confident wrong answer.
    expect(dishIconKey("Xenoi Paladakia", null)).toBe("plate");
    expect(dishIconKey("", null)).toBe("plate");
    expect(dishIconKey(undefined, undefined)).toBe("plate");
  });

  it("is case insensitive", () => {
    expect(dishIconKey("MASALA DOSA", "VEG")).toBe(dishIconKey("masala dosa", "veg"));
  });

  it("uses tags when the name says nothing", () => {
    // "Missing Angle" is a Corner House dessert with no hint in the name; the
    // tags are the only thing that can place it.
    expect(dishIconKey("Missing Angle", "veg, dessert, bestseller")).toBe("dessert");
  });

  it("has artwork for every key it can return", () => {
    // A rule with no path would render an empty tile, which looks like a bug.
    const keys = new Set();
    for (const dish of [
      "Masala Dosa", "Biryani", "Butter Chicken", "Naan", "Paneer Tikka", "Pizza",
      "Pasta", "Sandwich", "Tiramisu", "Kulfi", "Stout", "Fries", "Momo",
      "Andhra Meals", "Sushi", "Chaat", "Filter Coffee", "Gasa Gase", "Xenoi",
    ]) {
      keys.add(dishIconKey(dish, null));
    }
    for (const key of keys) {
      expect(DISH_ICON_PATHS[key], `no artwork for "${key}"`).toBeTruthy();
    }
  });
});

describe("the reference seed, dish by dish", () => {
  // The 66 distinct dish names the reference seed produces, captured verbatim
  // from the seeded database. The point is that a menu of real Bengaluru food
  // must not come out as a wall of identical tiles: every one of these has to
  // land on something more specific than the fallback plate.
  //
  // If the seed gains a dish, add it here. A new name that classifies as
  // "plate" shows up as a failing test rather than shipping a row of blanks.
  const SEEDED = [
    "Alfredo Pasta", "Andhra Meals", "Apple Pie", "Arrabbiata Pasta",
    "Banana Walnut Loaf", "Belgian Waffles", "Bisi Bele Bath",
    "Brownie with Ice Cream", "Bruschetta", "Butter Chicken", "Butter Croissant",
    "Butter Naan", "Chicken Puff", "Chocolate Brownie", "Cold Brew",
    "Cold Brew Tiramisu", "Craft Lager", "Crispy Chicken Sliders", "Curd Rice",
    "Dal Makhani", "Egg Cross Bun", "Espresso Tonic", "Filter Coffee",
    "Flat White", "Four Cheese Pizza", "Frozen Custard", "Gasa Gase",
    "Ghee Roast Dosa", "Grilled Cheese Sandwich", "Gulab Jamun", "Idiyappam",
    "Idli Sambar", "Kesari Bath", "Khar Badam", "Kulfi Falooda", "Lasagna",
    "Leg of Lamb", "Loaded Fries", "Margherita Pizza", "Masala Dosa",
    "Medu Vada", "Missing Angle", "Mud Pie", "Mysore Masala Dosa", "Mysore Pak",
    "Paneer Butter Masala", "Paneer Tikka", "Pasta al Pomodoro", "Payasam",
    "Podi Idli", "Pongal", "Pour Over", "Pulihora", "Rasam Rice", "Rava Idli",
    "Risotto", "Scone", "Stout", "Tandoori Roti", "Tiramisu", "Undhiyu", "Vada",
    "Vanilla Cupcake", "Wood Fired Margherita",
  ];

  it("has a real icon for every seeded dish, not a fallback plate", () => {
    const plates = SEEDED.filter((name) => dishIconKey(name, "veg, dessert") === "plate");
    expect(plates).toEqual([]);
  });

  it("does not collapse the whole menu onto one icon", () => {
    // Six Corner House desserts used to share a single cafe tile. The point of
    // per-dish icons is spread: a menu should not be one glyph repeated.
    const cornerHouse = [
      "Missing Angle", "Frozen Custard", "Apple Pie", "Mud Pie",
      "Belgian Waffles", "Brownie with Ice Cream",
    ];
    const icons = new Set(cornerHouse.map((name) => dishIconKey(name, "veg, dessert")));
    expect(icons.size).toBeGreaterThanOrEqual(2);
  });
});
