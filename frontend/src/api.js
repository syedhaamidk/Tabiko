const BASE_URL = "/api";
const TOKEN_KEY = "tabiko_token";
const REFRESH_KEY = "tabiko_refresh";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getRefreshToken() {
  return localStorage.getItem(REFRESH_KEY);
}

export function setTokens({ access_token, refresh_token }) {
  if (access_token) localStorage.setItem(TOKEN_KEY, access_token);
  if (refresh_token) localStorage.setItem(REFRESH_KEY, refresh_token);
}

/** Kept for callers that only have a bare access token, such as the test client. */
export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(REFRESH_KEY);
}

function authHeaders() {
  const token = getToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function handleResponse(res) {
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    let message = body;
    try {
      const parsed = JSON.parse(body);
      if (typeof parsed.detail === "string") message = parsed.detail;
      else if (Array.isArray(parsed.detail)) {
        message = parsed.detail.map((item) => item.msg).filter(Boolean).join("; ");
      }
    } catch {
      // Keep the raw response body when the API did not return JSON.
    }
    const error = new Error(message || `API error ${res.status}`);
    error.status = res.status;
    throw error;
  }
  if (res.status === 204) return null;
  return res.json();
}

/**
 * Exchange the refresh token for a new pair, at most once at a time.
 *
 * Access tokens are deliberately short-lived, so a session outlives several of
 * them. Without this the reader would be signed out every half hour; with it they
 * never notice. The shared promise is what stops several components refreshing
 * simultaneously from rotating the same token out from under each other.
 */
let refreshInFlight = null;

function refreshSession() {
  if (refreshInFlight) return refreshInFlight;
  const refreshToken = getRefreshToken();
  if (!refreshToken) return Promise.resolve(false);

  refreshInFlight = fetch(`${BASE_URL}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
    .then((res) => (res.ok ? res.json() : null))
    .then((body) => {
      if (!body) {
        // The session is genuinely over. Drop both halves so nothing keeps
        // retrying with a dead token.
        clearToken();
        return false;
      }
      setTokens(body);
      return true;
    })
    .catch(() => {
      // A refresh that never reached the server at all -- offline, DNS failure,
      // the connection dropped mid-tab. The original 401 is still what the
      // caller sees, so the reader is unaffected, but the token in storage is
      // not known to be dead and may well be valid.
      //
      // Clearing it here would be wrong: a train tunnel would sign the reader
      // out, and the token would have worked on the other side. What matters is
      // that a later request can try again, which it can, because `finally` has
      // already cleared the in-flight promise. So this returns false and
      // changes nothing.
      return false;
    })
    .finally(() => {
      refreshInFlight = null;
    });

  return refreshInFlight;
}

/**
 * Send an authenticated request, refreshing once if the access token has expired.
 *
 * The retry is what makes a 30-minute token invisible to the reader. It is
 * limited to a single attempt: if the refreshed token is also rejected the
 * session is not valid and retrying would loop.
 */
async function authFetch(path, options = {}, allowRetry = true) {
  const res = await fetch(path, { ...options, headers: { ...authHeaders(), ...(options.headers || {}) } });

  if (res.status === 401 && allowRetry && getRefreshToken()) {
    const refreshed = await refreshSession();
    if (refreshed) return authFetch(path, options, false);
  }
  return res;
}

// ---------- Auth ----------

export function register(name, email, password) {
  return fetch(`${BASE_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, email, password }),
  }).then(handleResponse);
}

export function login(email, password) {
  return fetch(`${BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  }).then(handleResponse);
}

export function getCurrentUser() {
  return authFetch(`${BASE_URL}/auth/me`).then(handleResponse);
}

export function updateProfile(reviewer_type, cuisine_specialty) {
  return authFetch(`${BASE_URL}/auth/me`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reviewer_type, cuisine_specialty }),
  }).then(handleResponse);
}

// ---------- Restaurants ----------

/**
 * Canonical filter vocabularies, owned by the backend. Falls back to nothing on
 * failure so the caller can use its bundled defaults instead of breaking.
 */
export function fetchFilterOptions() {
  return fetch(`${BASE_URL}/filter-options`).then(handleResponse);
}

/**
 * Lightweight map positions for the whole city.
 *
 * Deliberately separate from /restaurants: a full record for every place in
 * Bengaluru is megabytes, while a point is ~170 KB gzipped for all of them.
 */
export function fetchRestaurantPoints(filters = {}) {
  const params = new URLSearchParams(
    Object.fromEntries(Object.entries(filters).filter(([, value]) => value)),
  );
  return fetch(`${BASE_URL}/restaurants/points?${params}`).then(handleResponse);
}

/**
 * Counted numbers for the headline figures, so the hero states what is loaded
 * rather than a number frozen into a template.
 */
export function fetchStats() {
  return fetch(`${BASE_URL}/stats`).then(handleResponse);
}

/**
 * One page of cards, plus how many places matched in total.
 *
 * The count arrives in X-Total-Count, which the API only sets when a location
 * was supplied. Without one there is no meaningful total to show, so the page
 * length stands in and the UI stays quiet about totals it does not know.
 */
export function listRestaurants(filters = {}) {
  const params = new URLSearchParams(filters);
  return fetch(`${BASE_URL}/restaurants?${params}`).then((res) =>
    handleResponse(res).then((items) => ({
      items,
      total: res.headers.has("X-Total-Count")
        ? Number(res.headers.get("X-Total-Count"))
        : null,
    })),
  );
}

export function getRestaurant(id) {
  return fetch(`${BASE_URL}/restaurants/${id}`).then(handleResponse);
}

export function getRestaurantTheme(id) {
  return fetch(`${BASE_URL}/restaurants/${id}/theme`).then(handleResponse);
}

export function confirmMenu(id) {
  return authFetch(`${BASE_URL}/restaurants/${id}/confirm-menu`, {
    method: "PATCH",
  }).then(handleResponse);
}

// ---------- Dishes ----------

export function listDishes(restaurantId) {
  return fetch(`${BASE_URL}/restaurants/${restaurantId}/dishes`).then(handleResponse);
}

export function addDish(restaurantId, name, tags) {
  return authFetch(`${BASE_URL}/restaurants/${restaurantId}/dishes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    // An untouched tags box is "", not null. The server treats blank as absent
    // too, but sending null for "no value" is what the field means.
    body: JSON.stringify({ name, tags: tags?.trim() ? tags.trim() : null }),
  }).then(handleResponse);
}

/**
 * Add a whole pasted menu in one request.
 *
 * Duplicates come back in `skipped` rather than failing the batch, so the caller
 * has to show both halves or the reader cannot tell what landed.
 */
export function addDishesBulk(restaurantId, text) {
  return authFetch(`${BASE_URL}/restaurants/${restaurantId}/dishes/bulk`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  }).then(handleResponse);
}

// ---------- Reviews ----------

export function listReviews(restaurantId) {
  return fetch(`${BASE_URL}/reviews/restaurant/${restaurantId}`).then(handleResponse);
}

export function createReview(payload) {
  return authFetch(`${BASE_URL}/reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  }).then(handleResponse);
}

export function listFlaggedReviews() {
  return authFetch(`${BASE_URL}/reviews/flagged`).then(handleResponse);
}

// ---------- Saved places ----------

export function listFavorites() {
  return authFetch(`${BASE_URL}/favorites`).then(handleResponse);
}

export function saveFavorite(restaurantId) {
  return authFetch(`${BASE_URL}/favorites/${restaurantId}`, {
    method: "PUT",
  }).then(handleResponse);
}

export function removeFavorite(restaurantId) {
  return authFetch(`${BASE_URL}/favorites/${restaurantId}`, {
    method: "DELETE",
  }).then(handleResponse);
}

// ---------- Photo uploads ----------

/**
 * Upload one image and return the path the server will serve it from.
 *
 * Deliberately a separate call from submitting a dish or a review: the reader
 * picks a photo, it uploads immediately, and the review or dish is sent later
 * with the resulting path. That means a rejected image fails while the reader is
 * still looking at the picker, rather than after they have written the review.
 *
 * **The `Content-Type` header is not set, and that is not an oversight.** A
 * `multipart/form-data` body carries its boundary in the header, and only the
 * browser can generate that boundary. Setting the header by hand produces a
 * request the server cannot parse, with an error that reads like a server fault
 * rather than a client mistake. `fetch` sets it correctly when it is left alone.
 *
 * The file is sent as the raw request body rather than wrapped in `FormData`.
 * The server reads the bytes and sniffs them, so a field name and a filename add
 * nothing -- and a raw body is re-sendable, which matters because an expired
 * token makes `authFetch` send this request twice.
 */
export function uploadImage(file) {
  // A cheap guard on the declared type, before the bytes are sent. It is only
  // ever a shortcut: a reader who picked a .txt gets told while they can still
  // change the photo, rather than after a round trip. Anything the browser
  // claims might be an image goes to the server regardless, because the declared
  // type is not the file -- a renamed .txt says `image/png`, and the server's
  // magic-number check is the one that actually decides.
  if (file?.type && !file.type.startsWith("image/")) {
    return Promise.reject(
      new Error(`${file.name || "That file"} is not an image. Pick a photo.`),
    );
  }

  return authFetch(`${BASE_URL}/uploads`, {
    method: "POST",
    body: file,
  }).then(handleResponse);
}

// ---------- Following people ----------

/**
 * Follow state for one reader.
 *
 * Note what this does *not* do: the reviews list returns reviewer ids but not
 * whether the viewer follows them, so a page with several reviewers costs one
 * of these per reviewer. That is deliberate for now and is written up at the
 * bottom of the back-end's `tests/test_follows.py` with the three ways to
 * batch it. Do not "fix" it here by fetching it eagerly for every author on
 * mount -- that is the same N+1 with extra work before anything is visible.
 */
export function getFollowStatus(userId) {
  return authFetch(`${BASE_URL}/users/${userId}/follow-status`).then(handleResponse);
}

export function followUser(userId) {
  return authFetch(`${BASE_URL}/users/${userId}/follow`, {
    method: "POST",
  }).then(handleResponse);
}

export function unfollowUser(userId) {
  return authFetch(`${BASE_URL}/users/${userId}/follow`, {
    method: "DELETE",
  }).then(handleResponse);
}

export function listMyFollowing() {
  return authFetch(`${BASE_URL}/users/me/following`).then(handleResponse);
}

/** Reviews by people the signed-in reader follows, newest first. */
export function getFollowingFeed() {
  return authFetch(`${BASE_URL}/feed/following`).then(handleResponse);
}

/**
 * The reviews for one place, optionally narrowed to people the reader follows.
 *
 * `followingOnly` asks the server rather than filtering the returned list. The
 * alternative would send every review and hide most of them, which tells the
 * reader nothing about whether they follow anybody -- and the server has to know
 * the answer anyway to decide whether a signed-out reader gets a 401.
 */
export function getRestaurantReviews(restaurantId, { followingOnly = false } = {}) {
  const params = new URLSearchParams();
  if (followingOnly) params.set("following_only", "true");
  const query = params.toString();
  return authFetch(
    `${BASE_URL}/reviews/restaurant/${restaurantId}${query ? `?${query}` : ""}`,
  ).then(handleResponse);
}

export function logout() {
  const refresh = getRefreshToken();
  // Clear locally first: the reader asked to sign out, so the session is over
  // whether or not the server is reachable.
  clearToken();
  if (!refresh) return Promise.resolve(null);
  return fetch(`${BASE_URL}/auth/logout`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  }).catch(() => null);
}

/** The saved places as full card records, newest save first. */
export function listFavoritePlaces() {
  return authFetch(`${BASE_URL}/favorites/places`).then(handleResponse);
}

// ---------- Craving search ----------

export function searchByCraving(query) {
  const params = new URLSearchParams({ q: query });
  return fetch(`${BASE_URL}/search/craving?${params}`).then(handleResponse);
}
