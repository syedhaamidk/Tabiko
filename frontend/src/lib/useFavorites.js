import { useCallback, useEffect, useRef, useState } from "react";
import { listFavorites, removeFavorite, saveFavorite } from "../api";
import { useAuth } from "../AuthContext";

/**
 * The reader's saved places.
 *
 * One set is shared by the button on every card and the "saved only" filter, so
 * the two can never disagree about what is saved. Saving is optimistic because
 * the alternative is a button that feels broken on a slow connection, and it
 * rolls back if the request fails rather than silently drifting.
 *
 * Signing out clears the list: the next reader must not see the previous one's
 * shortlist.
 */
export default function useFavorites() {
  const { user, loading: authLoading } = useAuth();
  const [saved, setSaved] = useState(() => new Set());
  const [pending, setPending] = useState(() => new Set());
  const [loading, setLoading] = useState(false);

  // Mirrors `saved` so a fast double tap decides from the current state rather
  // than from whatever the last render closed over. It is written synchronously
  // inside `toggle` as well as on render, because two taps arriving in the same
  // tick would otherwise both read the pre-tap state and save twice.
  const savedRef = useRef(saved);
  savedRef.current = saved;

  useEffect(() => {
    if (authLoading) return;
    if (!user) {
      setSaved(new Set());
      setPending(new Set());
      return;
    }
    let active = true;
    setLoading(true);
    listFavorites()
      .then((rows) => {
        if (active) setSaved(new Set(rows.map((row) => row.restaurant_id)));
      })
      .catch(() => {
        // A failed read leaves the list empty rather than blocking the page; the
        // buttons still work and will repopulate it.
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [user, authLoading]);

  const toggle = useCallback(async (restaurantId) => {
    const wasSaved = savedRef.current.has(restaurantId);

    // Write the ref as well as the state, so a second tap in the same tick sees
    // the result of the first instead of both acting on the pre-tap set.
    const apply = (isSaved) => {
      const next = new Set(savedRef.current);
      if (isSaved) next.add(restaurantId);
      else next.delete(restaurantId);
      savedRef.current = next;
      setSaved(next);
    };

    apply(!wasSaved);
    setPending((previous) => new Set(previous).add(restaurantId));
    try {
      if (wasSaved) await removeFavorite(restaurantId);
      else await saveFavorite(restaurantId);
      return true;
    } catch {
      apply(wasSaved);
      return false;
    } finally {
      setPending((previous) => {
        const next = new Set(previous);
        next.delete(restaurantId);
        return next;
      });
    }
  }, []);

  return {
    saved,
    pending,
    loading,
    isSaved: (id) => saved.has(id),
    isPending: (id) => pending.has(id),
    count: saved.size,
    toggle,
    signedIn: Boolean(user),
  };
}
