import { useEffect, useState } from "react";
import {
  addDish,
  addDishesBulk,
  confirmMenu,
  createReview,
  getRestaurant,
  listDishes,
  listReviews,
} from "../api";
import { useTheme } from "../ThemeContext";
import { useAuth } from "../AuthContext";
import BrandMark from "./BrandMark";
import FoodGlyph from "../lib/foodIcons";
import InterfaceIcon from "./InterfaceIcon";
import {
  getRestaurantVisual,
  moneyTier,
  prettyTag,
} from "../lib/restaurantVisual";

function getCurrentPosition() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (position) =>
        resolve({
          lat: position.coords.latitude,
          lon: position.coords.longitude,
        }),
      () => resolve(null),
      { timeout: 5000, maximumAge: 60_000 },
    );
  });
}

const DIETARY_ICONS = {
  veg: "leaf",
  non_veg: "non-veg",
  vegan: "vegan",
  jain: "jain",
  halal: "halal",
};

function splitTags(value) {
  return (value || "")
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

function ReviewerBadges({ reviewer }) {
  return (
    <span className="reviewer-badges">
      {reviewer.reviewer_type === "food_critic" && (
        <span className="review-badge review-badge--critic">
          {reviewer.is_critic_verified ? "✓ Verified critic" : "Self-identified critic"}
        </span>
      )}
      {reviewer.reviewer_type === "cuisine_specialist" && reviewer.cuisine_specialty && (
        <span className="review-badge review-badge--specialist">
          {reviewer.cuisine_specialty} specialist
        </span>
      )}
      {reviewer.is_regular_here && (
        <span className="review-badge review-badge--regular">↻ Regular here</span>
      )}
      {reviewer.reviewer_type === "normal" && !reviewer.is_regular_here && (
        <span className="review-badge">Everyday diner</span>
      )}
    </span>
  );
}

export default function RestaurantDetail({ restaurantId, onBack }) {
  const { applyThemeForRestaurant, resetTheme } = useTheme();
  const { user } = useAuth();
  const [restaurant, setRestaurant] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [dishes, setDishes] = useState([]);
  const [reviews, setReviews] = useState([]);
  const [draft, setDraft] = useState({ rating: 5, text: "" });
  const [draftRequestId, setDraftRequestId] = useState(() => crypto.randomUUID());
  const [dishDraft, setDishDraft] = useState({ name: "", tags: "" });
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [locating, setLocating] = useState(false);
  const [actionError, setActionError] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    applyThemeForRestaurant(restaurantId);
    getRestaurant(restaurantId)
      .then((data) => !cancelled && setRestaurant(data))
      .catch((error) => !cancelled && setLoadError(error.message));
    listDishes(restaurantId)
      .then((data) => !cancelled && setDishes(data))
      .catch(() => {});
    listReviews(restaurantId)
      .then((data) => !cancelled && setReviews(data))
      .catch(() => {});
    return () => {
      cancelled = true;
      resetTheme();
    };
  }, [restaurantId, applyThemeForRestaurant, resetTheme]);

  async function handleSubmitReview(event) {
    event.preventDefault();
    if (!user) return;
    setSubmitting(true);
    setActionError(null);
    setLocating(true);
    const position = await getCurrentPosition();
    setLocating(false);
    try {
      const newReview = await createReview({
        restaurant_id: restaurantId,
        rating: Number(draft.rating),
        text: draft.text,
        user_lat: position?.lat,
        user_lon: position?.lon,
        client_request_id: draftRequestId,
      });
      setReviews((existing) => [newReview, ...existing]);
      setDraft({ rating: 5, text: "" });
      setDraftRequestId(crypto.randomUUID());
      getRestaurant(restaurantId).then(setRestaurant).catch(() => {});
    } catch (error) {
      setActionError(error.message || "Couldn't post your review.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleAddDish(event) {
    event.preventDefault();
    if (!dishDraft.name.trim()) return;
    setActionError(null);
    try {
      const dish = await addDish(restaurantId, dishDraft.name, dishDraft.tags);
      setDishes((existing) => [...existing, dish].sort((a, b) => a.name.localeCompare(b.name)));
      setDishDraft({ name: "", tags: "" });
    } catch (error) {
      setActionError(error.message || "Couldn't add that dish.");
    }
  }

  async function handleBulkSubmit(event) {
    event.preventDefault();
    if (!bulkText.trim()) return;
    setActionError(null);
    setBulkBusy(true);
    try {
      const result = await addDishesBulk(restaurantId, bulkText);
      setDishes((existing) =>
        [...existing, ...result.added].sort((a, b) => a.name.localeCompare(b.name)),
      );
      setBulkResult(result);
      // A menu that just changed is not "freshly confirmed", so re-read the
      // place rather than leaving a stale claim on screen.
      getRestaurant(restaurantId).then(setRestaurant).catch(() => {});
      if (result.added.length > 0) setBulkText("");
    } catch (error) {
      setActionError(error.message || "Couldn't add that menu.");
    } finally {
      setBulkBusy(false);
    }
  }

  async function handleCopyLink() {
    const url = `${window.location.origin}${window.location.pathname}#restaurant-${restaurantId}`;
    let success = false;
    try {
      await navigator.clipboard.writeText(url);
      success = true;
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = url;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      success = document.execCommand("copy");
      textarea.remove();
    }
    if (success) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } else {
      setActionError("Could not copy the link — your browser blocked the clipboard.");
    }
  }

  async function handleConfirmMenu() {
    setActionError(null);
    try {
      setRestaurant(await confirmMenu(restaurantId));
    } catch (error) {
      setActionError(error.message || "Couldn't confirm the menu.");
    }
  }

  if (loadError) {
    return (
      <div className="detail-state error-state" role="alert">
        <InterfaceIcon name="location" size={30} />
        <strong>That flavor card slipped away.</strong>
        <button className="app-button" onClick={onBack}>Back to the party</button>
      </div>
    );
  }

  if (!restaurant) {
    return (
      <div className="detail-state loading-state" role="status">
        <span className="loading-plate" aria-hidden="true">
          <BrandMark size={54} />
        </span>
        <strong>Plating the details…</strong>
      </div>
    );
  }

  const visual = getRestaurantVisual(restaurant);
  const cuisines = splitTags(restaurant.cuisine_tags);
  const dietary = splitTags(restaurant.dietary_flags);
  const goodFor = splitTags(restaurant.good_for);
  const accessibility = splitTags(restaurant.accessibility_flags);
  const price = moneyTier(restaurant.price_tier);
  const menuIsStale =
    !restaurant.menu_last_confirmed ||
    (Date.now() - new Date(restaurant.menu_last_confirmed).getTime()) / 86_400_000 > 90;

  return (
    <main
      className="restaurant-detail"
      style={{ "--detail-color": visual.color, "--detail-accent": visual.accent }}
    >
      <div className="restaurant-detail__toolbar">
        <button className="back-button" onClick={onBack}>
          <span aria-hidden="true">←</span> Back to the party
        </button>
        <div className="detail-toolbar__actions">
          <span className="source-chip"><InterfaceIcon name="pin" size={15} /> Tabiko place intel</span>
          <button className="app-button share-button" onClick={handleCopyLink}>
            {copied ? "Link copied ✓" : "Copy the vibe"}
          </button>
        </div>
      </div>

      <section className="detail-hero">
        <span className="detail-hero__tape" aria-hidden="true" />
        <span className="detail-hero__burst" aria-hidden="true">MUST<br />TRY!</span>
        <span className="detail-hero__ticker" aria-hidden="true">★ STREET FOOD ★ NO BORING BITES ★</span>
        <div className="detail-hero__emoji" aria-hidden="true">
          <FoodGlyph visual={visual} size={124} instanceId={`hero-${restaurant.id}`} />
        </div>
        <div className="detail-hero__copy">
          <span className="section-kicker">{visual.label}</span>
          <h1>{restaurant.name}</h1>
          <p>{restaurant.address || "Bengaluru, Karnataka"}</p>
          <div className="tag-row">
            {cuisines.map((cuisine) => (
              <span className="tag-pill" key={cuisine}>{prettyTag(cuisine)}</span>
            ))}
            {dietary.map((flag) => (
              <span className="tag-pill tag-pill--diet" key={flag}>
                <InterfaceIcon name={DIETARY_ICONS[flag.toLowerCase()]} size={13} />
                {prettyTag(flag)}
              </span>
            ))}
          </div>
        </div>
        <div className="detail-hero__stamp" aria-hidden="true">
          <span>Tabiko</span>
          <strong>find the funk</strong>
          <small>eat local</small>
        </div>
      </section>

      <section className="fact-grid" aria-label="Restaurant highlights">
        <div className="fact-card">
          <InterfaceIcon name="plate" size={21} />
          <div><small>Place</small><strong>{prettyTag(restaurant.type_tag)}</strong></div>
        </div>
        {price && (
          <div className="fact-card">
            <InterfaceIcon name="qsr" size={21} />
            <div><small>Price</small><strong>{price}</strong></div>
          </div>
        )}
        {restaurant.noise_level && restaurant.noise_level !== "unknown" && (
          <div className="fact-card">
            <InterfaceIcon name="layers" size={21} />
            <div><small>Noise</small><strong>{prettyTag(restaurant.noise_level)}</strong></div>
          </div>
        )}
        {goodFor.length > 0 && (
          <div className="fact-card">
            <InterfaceIcon name="date" size={21} />
            <div><small>Good for</small><strong>{goodFor.map(prettyTag).join(", ")}</strong></div>
          </div>
        )}
        {accessibility.length > 0 && (
          <div className="fact-card">
            <InterfaceIcon name="location" size={21} />
            <div><small>Access</small><strong>{accessibility.map(prettyTag).join(", ")}</strong></div>
          </div>
        )}
        {restaurant.hygiene_score != null && (
          <div className="fact-card">
            <InterfaceIcon name="leaf" size={21} />
            <div><small>Freshness</small><strong>{restaurant.hygiene_score.toFixed(1)} / 5</strong></div>
          </div>
        )}
      </section>

      {actionError && (
        <div className="inline-alert" role="alert">
          <InterfaceIcon name="sparkles" size={16} /> {actionError}
        </div>
      )}

      <div className="detail-columns">
        <section className="detail-panel" aria-labelledby="dishes-heading">
          <div className="detail-panel__heading">
            <div>
              <span className="section-kicker">On the menu</span>
              <h2 id="dishes-heading">The menu, minus the mystery</h2>
            </div>
            <span className="menu-freshness">
              <InterfaceIcon name={menuIsStale ? "search" : "check"} size={14} />
              {menuIsStale ? "Flavor check needed" : "Freshly confirmed"}
            </span>
          </div>

          {user && (
            <button className="confirm-menu-button" onClick={handleConfirmMenu}>
              <InterfaceIcon name="check" size={16} />
              {menuIsStale ? "I vouch for this menu" : "Vouch for the menu again"}
            </button>
          )}

          {dishes.length === 0 ? (
            <div className="panel-empty panel-empty--invite">
              <InterfaceIcon name="plate" size={22} />
              {user ? (
                <>
                  <strong>Nobody has written this menu down yet.</strong>
                  <p>
                    If you have eaten here, you know what they serve. Add it and
                    everyone after you gets the answer without walking in blind.
                  </p>
                  <button
                    className="app-button app-button--primary"
                    type="button"
                    onClick={() => {
                      setBulkOpen(true);
                      setBulkResult(null);
                    }}
                  >
                    <InterfaceIcon name="plus" size={16} />
                    Add the menu
                  </button>
                </>
              ) : (
                <>
                  <strong>Nobody has written this menu down yet.</strong>
                  <p>Log in and add what they serve, so the next person does not have to guess.</p>
                </>
              )}
            </div>
          ) : (
            <div className="dish-grid">
              {dishes.map((dish) => (
                <article className="dish-card" key={dish.id}>
                  <div className="dish-card__top">
                    <FoodGlyph
                      visual={visual}
                      size={34}
                      instanceId={`dish-${dish.id}`}
                    />
                    <span className="dish-card__rating">
                      {dish.avg_rating > 0 ? `${dish.avg_rating.toFixed(1)}★` : "New"}
                    </span>
                  </div>
                  <h3>{dish.name}</h3>
                  {dish.tags && <p>{dish.tags.replace(/,/g, " · ")}</p>}
                  <small>{dish.review_count} review{dish.review_count === 1 ? "" : "s"}</small>
                  {dish.added_by && (
                    <small className="dish-card__credit">
                      Added by {dish.added_by.name}
                      {dish.added_by.is_critic_verified ? " · verified critic" : ""}
                    </small>
                  )}
                </article>
              ))}
            </div>
          )}

          {user && dishes.length > 0 && (
            <div className="bulk-toggle">
              <button
                className="app-button app-button--ghost"
                type="button"
                aria-expanded={bulkOpen}
                onClick={() => {
                  setBulkOpen((open) => !open);
                  setBulkResult(null);
                }}
              >
                <InterfaceIcon name={bulkOpen ? "close" : "plus"} size={16} />
                {bulkOpen ? "Cancel" : "Add a whole menu"}
              </button>
            </div>
          )}

          {user && bulkOpen && (
            <form className="bulk-menu-form" onSubmit={handleBulkSubmit}>
              <label htmlFor="bulk-menu-text">
                Paste the menu — one dish per line, tags after a comma
              </label>
              <textarea
                id="bulk-menu-text"
                rows={7}
                placeholder={"Masala Dosa, veg, breakfast\nFilter Coffee\nVada, veg, breakfast"}
                value={bulkText}
                onChange={(event) => setBulkText(event.target.value)}
              />
              <div className="bulk-menu-form__actions">
                <button
                  className="app-button app-button--primary"
                  type="submit"
                  disabled={bulkBusy || !bulkText.trim()}
                >
                  {bulkBusy ? "Adding…" : "Add them all"}
                </button>
                <span className="bulk-menu-form__hint">
                  Anything already on the menu is skipped, not rejected.
                </span>
              </div>
            </form>
          )}

          {bulkResult && (
            <p className="bulk-menu-result" role="status">
              {bulkResult.added.length > 0
                ? `Added ${bulkResult.added.length} dish${bulkResult.added.length === 1 ? "" : "es"}.`
                : "Nothing new to add."}
              {bulkResult.skipped.length > 0 &&
                ` Already on the menu: ${bulkResult.skipped.join(", ")}.`}
            </p>
          )}

          {user && (
            <form className="add-dish-form" onSubmit={handleAddDish}>
              <input
                aria-label="Dish name"
                placeholder="Add a dish — Masala Dosa?"
                value={dishDraft.name}
                onChange={(event) => setDishDraft((draft) => ({ ...draft, name: event.target.value }))}
              />
              <input
                aria-label="Dish tags"
                placeholder="Tags: spicy, veg, bestseller"
                value={dishDraft.tags}
                onChange={(event) => setDishDraft((draft) => ({ ...draft, tags: event.target.value }))}
              />
              <button className="app-button app-button--primary" type="submit">Add dish</button>
            </form>
          )}
        </section>

        <section className="detail-panel detail-panel--reviews" aria-labelledby="reviews-heading">
          <div className="detail-panel__heading">
            <div>
              <span className="section-kicker">Community notes</span>
              <h2 id="reviews-heading">Word on the street</h2>
            </div>
            <span className="review-total">{reviews.length} shown</span>
          </div>

          {user ? (
            <form className="review-composer" onSubmit={handleSubmitReview}>
              <div className="review-composer__rating">
                <label htmlFor="review-rating">Your rating</label>
                <select
                  id="review-rating"
                  value={draft.rating}
                  onChange={(event) => setDraft((draft) => ({ ...draft, rating: event.target.value }))}
                >
                  {[5, 4, 3, 2, 1].map((rating) => (
                    <option key={rating} value={rating}>{rating} ★</option>
                  ))}
                </select>
              </div>
              <textarea
                aria-label="Review text"
                placeholder="What did you order? What should the next person know?"
                value={draft.text}
                onChange={(event) => setDraft((draft) => ({ ...draft, text: event.target.value }))}
                rows={4}
              />
              <div className="review-composer__footer">
                <small><InterfaceIcon name="pin" size={14} /> Nearby check-ins earn a here-now badge.</small>
                <button className="app-button app-button--primary" type="submit" disabled={submitting}>
                  {locating ? "Checking nearby…" : submitting ? "Dropping…" : "Drop a note"}
                </button>
              </div>
            </form>
          ) : (
            <div className="panel-empty">
              <InterfaceIcon name="solo" size={22} />
              Log in above to leave a review or add a dish.
            </div>
          )}

          <div className="review-list">
            {reviews.length === 0 ? (
              <div className="panel-empty">
                <InterfaceIcon name="sparkles" size={22} />
                Be the first neighbor to leave a flavor note.
              </div>
            ) : (
              reviews.map((review) => (
                <article className="review-card" key={review.id}>
                  <div className="review-card__top">
                    <span className="review-card__avatar" aria-hidden="true">
                      {review.reviewer.name.slice(0, 1).toUpperCase()}
                    </span>
                    <div>
                      <strong>{review.reviewer.name}</strong>
                      <ReviewerBadges reviewer={review.reviewer} />
                    </div>
                    <span className="review-card__rating">{review.rating}★</span>
                  </div>
                  <p>{review.text || "No written review — just a rating."}</p>
                  <div className="review-card__meta">
                    <span className={review.verification_tier === "checked_in" ? "is-verified" : ""}>
                      {review.verification_tier === "checked_in" && <InterfaceIcon name="pin" size={13} />}
                      {review.verification_tier === "checked_in" ? "Nearby check-in" : prettyTag(review.verification_tier)}
                    </span>
                    <time dateTime={review.created_at}>
                      {new Date(review.created_at).toLocaleDateString("en-IN", {
                        day: "numeric",
                        month: "short",
                        year: "numeric",
                      })}
                    </time>
                  </div>
                </article>
              ))
            )}
          </div>
        </section>
      </div>
    </main>
  );
}
