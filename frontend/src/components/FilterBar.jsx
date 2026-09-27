import { useEffect, useState } from "react";
import InterfaceSelect from "./InterfaceSelect";
import { fetchFilterOptions } from "../api";
import { CANONICAL_CUISINES, cuisinePresentation } from "../lib/cuisinePresentation";

/**
 * Filter vocabularies.
 *
 * The values must be exactly what the API accepts, so they are the canonical
 * lists from the backend rather than a hand-typed copy. `label` and `icon` are
 * presentation only and live here.
 *
 * `/filter-options` is the single source of truth: cuisine comes from the
 * classifier's canonical labels and venue types from the RestaurantType enum, so
 * a value that appears in this menu can never be rejected by the API.
 */

const TYPE_PRESENTATION = {
  cafe: ["Cafe & bakery", "coffee"],
  family_restaurant: ["Family restaurant", "family"],
  fine_dine: ["Fine dining", "fine-dine"],
  cloud_kitchen: ["Cloud kitchen", "cloud-kitchen"],
  darshini_qsr: ["Darshini / QSR", "qsr"],
  bar_microbrewery: ["Bar / microbrewery", "bar"],
  food_court_stall: ["Food court stall", "stall"],
  canteen: ["Canteen", "canteen"],
  dhaba: ["Dhaba / roadside", "dhaba"],
  street_stall: ["Street stall", "street-stall"],
  hotel_restaurant: ["Hotel restaurant", "hotel-restaurant"],
  takeaway: ["Takeaway counter", "takeaway"],
  unclassified: ["Not classified yet", "sparkles"],
};

const DIET_PRESENTATION = {
  veg: ["Vegetarian", "leaf"],
  non_veg: ["Non-vegetarian", "non-veg"],
  vegan: ["Vegan", "vegan"],
  jain: ["Jain", "jain"],
  halal: ["Halal", "halal"],
  egg: ["Egg served", "egg"],
  gluten_free: ["Gluten-free options", "gluten-free"],
};

const GOOD_FOR_PRESENTATION = {
  date: ["Date night", "date"],
  solo: ["Solo dining", "solo"],
  group: ["Groups", "group"],
  family: ["Family & kids", "kids"],
  work: ["Working & studying", "work"],
  late_night: ["Late night", "late-night"],
  outdoor: ["Outdoor seating", "outdoor"],
  pet_friendly: ["Pet friendly", "pets"],
  budget: ["Budget friendly", "budget"],
  quick_bite: ["Quick bite", "quick-bite"],
  live_music: ["Live music", "live-music"],
};

const ACCESSIBILITY_PRESENTATION = {
  wheelchair_accessible: ["Step-free access", "access"],
  not_wheelchair_accessible: ["Not step-free", "blocked"],
  seating: ["Seating available", "seating"],
};

// Used until /filter-options answers, and if it cannot be reached. Every group
// the bar renders needs a key here, or the offline path throws.
const FALLBACK = {
  cuisine: CANONICAL_CUISINES,
  type_tag: Object.keys(TYPE_PRESENTATION),
  dietary: Object.keys(DIET_PRESENTATION),
  good_for: Object.keys(GOOD_FOR_PRESENTATION),
  accessibility: Object.keys(ACCESSIBILITY_PRESENTATION),
};

const PRESENTATION = {
  type_tag: TYPE_PRESENTATION,
  dietary: DIET_PRESENTATION,
  good_for: GOOD_FOR_PRESENTATION,
  accessibility: ACCESSIBILITY_PRESENTATION,
};

function toOptions(group, values, counts) {
  const table = PRESENTATION[group];
  const source = values?.length ? values : FALLBACK[group];
  return source.map((value, index) => {
    let label;
    let icon;
    if (group === "cuisine") {
      ({ label, icon } = cuisinePresentation(value));
    } else {
      [label, icon] = table[value] ?? [value.replace(/_/g, " "), "sparkles"];
    }
    // Keep backend ordering, but never ship an option with no label.
    // `count` is how many places in the whole city carry this value. An option
    // at zero would return an empty page, so it is shown as such rather than
    // dropped: the vocabulary is canonical, and hiding a value would hide the
    // fact that the data does not cover it.
    return { value, label, icon, key: `${value}-${index}`, count: counts?.[value] };
  });
}

export default function FilterBar({ filters, onChange, disabled }) {
  const [available, setAvailable] = useState(null);

  useEffect(() => {
    let active = true;
    fetchFilterOptions()
      .then((options) => {
        if (active) setAvailable(options);
      })
      .catch(() => {
        // Keep the bundled fallback so filtering still works offline.
        if (active) setAvailable(null);
      });
    return () => {
      active = false;
    };
  }, []);

  const update = (key, value) => onChange({ ...filters, [key]: value });

  return (
    <section className="filter-shell" aria-label="Restaurant filters">
      <div className="filter-shell__heading">
        <div>
          <span className="section-kicker">Set the mood</span>
          <strong>Filter the funk</strong>
        </div>
        <span className="filter-shell__hint">
          {available?.total_places != null
            ? `${available.total_places.toLocaleString("en-IN")} places · counts are city-wide`
            : "Choose more than one vibe to narrow the table"}
        </span>
      </div>
      <div className="filter-bar">
        <InterfaceSelect
          label="Cuisine"
          value={filters.cuisine}
          placeholder="Any cuisine"
          options={toOptions("cuisine", available?.cuisine, available?.counts?.cuisine)}
          onChange={(value) => update("cuisine", value)}
          disabled={disabled}
          searchable
        />
        <InterfaceSelect
          label="Place"
          value={filters.type_tag}
          placeholder="Any venue"
          options={toOptions("type_tag", available?.type_tag, available?.counts?.type_tag)}
          onChange={(value) => update("type_tag", value)}
          disabled={disabled}
          searchable
        />
        <InterfaceSelect
          label="Diet"
          value={filters.dietary}
          placeholder="Any diet"
          options={toOptions("dietary", available?.dietary, available?.counts?.dietary)}
          onChange={(value) => update("dietary", value)}
          disabled={disabled}
        />
        <InterfaceSelect
          label="Good for"
          value={filters.good_for}
          placeholder="Any occasion"
          options={toOptions("good_for", available?.good_for, available?.counts?.good_for)}
          onChange={(value) => update("good_for", value)}
          disabled={disabled}
          searchable
        />
        <InterfaceSelect
          label="Access"
          value={filters.accessibility}
          placeholder="Any access need"
          options={toOptions(
            "accessibility",
            available?.accessibility,
            available?.counts?.accessibility,
          )}
          onChange={(value) => update("accessibility", value)}
          disabled={disabled}
        />
      </div>
      {disabled && <p className="filter-note">Filters pause while craving radar is active</p>}
    </section>
  );
}
