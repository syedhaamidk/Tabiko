import { useCallback, useEffect, useRef, useState } from "react";
import { followUser, getFollowStatus, unfollowUser } from "../api";
import { useAuth } from "../AuthContext";

/**
 * Follow or unfollow the person who wrote a review.
 *
 * Renders nothing when nobody is signed in, because the endpoint needs an
 * account and a button that always fails when tapped is worse than no button.
 *
 * **The follow state is fetched per reviewer, not batched.** That is the known
 * N+1: a page with six reviews from six people makes six requests. It is
 * documented rather than solved, with the three ways to batch it and why none is
 * free, at the bottom of the back end's `tests/test_follows.py`. What this
 * component does do is keep that cost honest in three ways, which is the part
 * worth having in the front end at all:
 *
 *  - It asks once per reviewer even when several reviews share one author. The
 *    cache holds the *promise*, not the answer, so a page that renders four
 *    reviews from two people before either request returns makes two requests.
 *    Caching only the resolved value -- which is the obvious thing to do -- lets
 *    every button in the same render pass fire its own, which is the N+1 with an
 *    extra layer of surprise on top.
 *  - It never re-fetches after a click, because it already knows the answer --
 *    the button updates from the click rather than from a round trip, so it is
 *    never briefly wrong.
 */
const statusCache = new Map();

/** Test seam: the cache is module state, and a test must not inherit it. */
export function _clearFollowCache() {
  statusCache.clear();
}

export default function FollowButton({ userId, name, compact = false, onChange }) {
  const { user } = useAuth();
  const [isFollowing, setIsFollowing] = useState(() => {
    const cached = statusCache.get(userId);
    return cached && typeof cached !== "object" ? cached : undefined;
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const isSelf = user && user.id === userId;

  const load = useCallback(async () => {
    if (isSelf || !user) return;
    // Anything already in the cache is either a known answer or a request
    // already in flight. Either way, this button has nothing left to ask.
    if (statusCache.has(userId)) return;

    const pending = getFollowStatus(userId)
      .then((answer) => answer.is_following)
      .catch(() => undefined);

    // Cached as a promise *before* awaiting, so a second button for the same
    // author in the same render pass attaches to this request instead of
    // starting its own.
    statusCache.set(userId, pending);

    const result = await pending;

    // Ownership check, and the only place that publishes an answer. A click that
    // landed while this was in flight replaced the cache entry, and the reader's
    // own answer is newer than anything this lookup learned -- so a late
    // response must not overwrite it, and a late response must not be able to
    // undo the check that lets it through in the first place. (Writing the
    // answer from inside the `.then` above, before this guard, made the two
    // conditions mutually exclusive and the state never updated at all.)
    if (statusCache.get(userId) !== pending) return;

    if (typeof result === "boolean") {
      statusCache.set(userId, result);
      if (mounted.current) setIsFollowing(result);
    } else {
      // Forget the failure so a later mount can try again. The button keeps its
      // default state, which reads as "not following" and is the safe
      // direction: the worst case is a reader taps follow for someone they
      // already follow, and the endpoint is idempotent.
      statusCache.delete(userId);
    }
  }, [user, userId, isSelf]);

  useEffect(() => {
    load();
  }, [load]);

  async function toggle() {
    if (busy) return;
    setBusy(true);
    setError(null);
    // Update from the click, not from the response. Waiting for the round trip
    // to flip a label is the difference between a button and a loading spinner.
    const next = !isFollowing;
    setIsFollowing(next);
    statusCache.set(userId, next);
    // Told immediately rather than after the response, so a list filtered to
    // "people I follow" can drop or add this author without waiting.
    onChange?.({ userId, isFollowing: next });
    try {
      const status = next ? await followUser(userId) : await unfollowUser(userId);
      if (!mounted.current) return;
      // Trust the server's answer over the guess: it is the only thing that
      // knows the true counts, and a follow that failed is worth reverting.
      statusCache.set(userId, status.is_following);
      setIsFollowing(status.is_following);
      if (status.is_following !== next) {
        onChange?.({ userId, isFollowing: status.is_following });
      }
    } catch (caught) {
      if (!mounted.current) return;
      statusCache.set(userId, !next);
      setIsFollowing(!next);
      // Put the caller's view back too, or a filtered list keeps showing a
      // review from someone the reader is no longer following.
      onChange?.({ userId, isFollowing: !next });
      // Surfaced rather than swallowed, because a button that silently snaps
      // back and says nothing is the most confusing failure there is.
      setError(caught.message || "That did not work. Try again.");
    }
    setBusy(false);
  }

  if (!user || isSelf) return null;

  return (
    <span className="follow">
      <button
        type="button"
        className={`follow__button ${isFollowing ? "is-following" : ""} ${
          compact ? "is-compact" : ""
        }`}
        onClick={toggle}
        disabled={busy}
        aria-pressed={Boolean(isFollowing)}
        data-testid={`follow-${userId}`}
      >
        {isFollowing ? "Following" : "Follow"}
        {/* Always named, even when compact. A review list renders one of these
            per review, and a screen reader announcing three buttons all called
            "Follow" is no use to anyone. The name is visually hidden rather
            than omitted, so the compact sizing is unaffected. */}
        {name ? <span className="sr-only"> {name}</span> : null}
      </button>
      {error ? (
        <span className="follow__error" role="alert">
          {error}
        </span>
      ) : null}
    </span>
  );
}
