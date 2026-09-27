import { useCallback, useEffect, useState } from "react";
import { getFollowingFeed, listMyFollowing } from "../api";
import FollowButton from "./FollowButton";
import InterfaceIcon from "./InterfaceIcon";
import { useAuth } from "../AuthContext";

/**
 * Reviews from people the reader follows, newest first.
 *
 * Strictly chronological, and that is a decision rather than a missing feature.
 * A feed that ranked by some notion of relevance would need a way to explain
 * itself, and "we decided to show you this" is the one answer a reader of a
 * food app has no way to check. So: newest first, and nothing clever.
 *
 * The empty state is where most of the work is. There are three distinct
 * reasons this can be empty and they need different words, because "no reviews"
 * on its own leaves a reader thinking the feature is broken:
 *
 *   - signed out, which should not be reachable but is handled anyway,
 *   - following nobody, which is a first-run state and wants an explanation,
 *   - following people who have not reviewed anything, which wants a link to
 *     finding people rather than a suggestion to try harder.
 */
export default function FriendsFeed({ onOpenRestaurant }) {
  const { user, loading } = useAuth();
  const [entries, setEntries] = useState([]);
  const [following, setFollowing] = useState([]);
  const [error, setError] = useState(null);
  const [loadingFeed, setLoadingFeed] = useState(true);
  // Bumped on every follow change, because the feed is exactly the set of
  // reviews by people the reader follows. Unfollowing the last person who has
  // reviewed anything should empty this view, not leave it stale.
  const [followsVersion, setFollowsVersion] = useState(0);

  const onFollowChange = useCallback(() => {
    setFollowsVersion((value) => value + 1);
  }, []);

  useEffect(() => {
    if (!user) {
      setLoadingFeed(false);
      return undefined;
    }

    let cancelled = false;
    setLoadingFeed(true);
    setError(null);

    getFollowingFeed()
      .then((data) => {
        if (cancelled) return;
        setEntries(data.entries || []);
      })
      .catch((caught) => {
        if (cancelled) return;
        setEntries([]);
        setError(caught.message || "Could not load your feed.");
      })
      .finally(() => !cancelled && setLoadingFeed(false));

    // The list of people is what turns an empty feed into an explanation
    // rather than a shrug, so it is fetched alongside and not lazily.
    listMyFollowing()
      .then((data) => !cancelled && setFollowing(data.users || []))
      .catch(() => {
        // Not load-bearing. Without it the empty state falls back to the
        // generic wording, which is a worse answer but not a wrong one.
      });

    return () => {
      cancelled = true;
    };
  }, [user, followsVersion]);

  if (loading || loadingFeed) {
    return (
      <section className="friends-feed">
        <div className="panel-empty">Loading what your people are eating…</div>
      </section>
    );
  }

  if (!user) {
    return (
      <section className="friends-feed">
        <div className="panel-empty">
          <InterfaceIcon name="solo" size={22} />
          Sign in to see reviews from the people you follow.
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <section className="friends-feed">
        <div className="panel-empty" role="alert">
          <InterfaceIcon name="solo" size={22} />
          {error}
        </div>
      </section>
    );
  }

  if (entries.length === 0) {
    return (
      <section className="friends-feed">
        <div className="panel-empty">
          <InterfaceIcon name="sparkles" size={22} />
          {following.length === 0 ? (
            <>
              You are not following anyone yet. Follow a few people on a place
              you like, and their notes will collect here.
            </>
          ) : (
            <>
              You follow {following.length}{" "}
              {following.length === 1 ? "person" : "people"}, and none of them
              have reviewed anywhere yet. Their notes will show up here.
            </>
          )}
        </div>
        {following.length > 0 ? (
          <ul className="following-list">
            {following.map((person) => (
              <li key={person.id}>
                <span>{person.name}</span>
                <FollowButton
                  userId={person.id}
                  name={person.name}
                  compact
                  onChange={onFollowChange}
                />
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    );
  }

  return (
    <section className="friends-feed">
      <ol className="feed-list">
        {entries.map((entry) => (
          <li key={entry.review.id}>
            <article className="review-card">
              <div className="review-card__top">
                <span className="review-card__avatar" aria-hidden="true">
                  {entry.review.reviewer.name.slice(0, 1).toUpperCase()}
                </span>
                <div>
                  <strong>{entry.review.reviewer.name}</strong>
                  <button
                    type="button"
                    className="feed-place"
                    onClick={() =>
                      onOpenRestaurant &&
                      onOpenRestaurant(entry.review.restaurant_id)
                    }
                  >
                    {entry.restaurant_name}
                  </button>
                </div>
                <FollowButton
                  userId={entry.review.reviewer.id}
                  name={entry.review.reviewer.name}
                  compact
                  onChange={onFollowChange}
                />
                <span className="review-card__rating">{entry.review.rating}★</span>
              </div>
              <p>{entry.review.text || "No written review — just a rating."}</p>
              <div className="review-card__meta">
                <time dateTime={entry.review.created_at}>
                  {new Date(entry.review.created_at).toLocaleDateString("en-IN", {
                    day: "numeric",
                    month: "short",
                    year: "numeric",
                  })}
                </time>
              </div>
            </article>
          </li>
        ))}
      </ol>
    </section>
  );
}
