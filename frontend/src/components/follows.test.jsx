/**
 * The follow button and the friends feed.
 *
 * The button carries the known N+1 -- one status request per reviewer, documented
 * at the bottom of the back end's `tests/test_follows.py` -- so the tests here
 * are mostly about making that cost behave: fetched once per reviewer, cached,
 * and never fetched again after a click that already knows the answer.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getFollowStatus: vi.fn(),
  followUser: vi.fn(),
  unfollowUser: vi.fn(),
  getFollowingFeed: vi.fn(),
  listMyFollowing: vi.fn(),
}));

const authState = vi.hoisted(() => ({ user: null, loading: false }));

vi.mock("../api", () => api);

vi.mock("../AuthContext", () => ({
  useAuth: () => ({ user: authState.user, loading: authState.loading }),
}));

import FollowButton, { _clearFollowCache } from "./FollowButton";
import FriendsFeed from "./FriendsFeed";

const ME = { id: 1, name: "Asha" };
const BALA = { id: 2, name: "Bala" };
const DIVYA = { id: 3, name: "Divya" };

const status = (isFollowing) => ({
  is_following: isFollowing,
  follower_count: isFollowing ? 1 : 0,
  following_count: 0,
});

const review = (id, author, text, daysAgo = 1) => ({
  review: {
    id,
    user_id: author.id,
    restaurant_id: 10,
    rating: 5,
    text,
    verification_tier: "unverified",
    fraud_flag: false,
    created_at: new Date(Date.now() - daysAgo * 86400000).toISOString(),
    image_url: null,
    reviewer: {
      id: author.id,
      name: author.name,
      reviewer_type: "normal",
      is_critic_verified: false,
      cuisine_specialty: null,
      is_regular_here: false,
    },
  },
  restaurant_name: "Corner House",
  restaurant_cuisine: "modern_indian",
  restaurant_latitude: 12.9,
  restaurant_longitude: 77.6,
});

beforeEach(() => {
  _clearFollowCache();
  authState.user = ME;
  authState.loading = false;
  api.getFollowStatus.mockResolvedValue(status(false));
  api.followUser.mockResolvedValue(status(true));
  api.unfollowUser.mockResolvedValue(status(false));
  api.getFollowingFeed.mockResolvedValue({ entries: [], count: 0 });
  api.listMyFollowing.mockResolvedValue({ users: [], count: 0 });
});

afterEach(() => {
  vi.clearAllMocks();
});

// ---------- FollowButton ----------

describe("FollowButton", () => {
  it("names who it follows even when compact", async () => {
    // A review list renders one of these per review, and a screen reader
    // announcing three buttons all called "Follow" is no use to anyone. The
    // name is visually hidden, not omitted.
    render(
      <>
        <FollowButton userId={BALA.id} name="Bala" compact />
        <FollowButton userId={DIVYA.id} name="Divya" compact />
      </>,
    );

    expect(await screen.findByRole("button", { name: /^follow bala$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^follow divya$/i })).toBeInTheDocument();
  });

  it("starts out un-following and says so", async () => {
    api.getFollowStatus.mockResolvedValue(status(false));
    render(<FollowButton userId={BALA.id} name="Bala" />);

    expect(await screen.findByRole("button", { name: /follow/i })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("reads an existing follow rather than assuming there is none", async () => {
    api.getFollowStatus.mockResolvedValue(status(true));
    render(<FollowButton userId={BALA.id} name="Bala" />);

    expect(
      await screen.findByRole("button", { name: /following/i }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("follows, and updates from the click rather than waiting for the response", async () => {
    const user = userEvent.setup();
    // A promise that is never settled, so any "wait for the response" would hang.
    api.followUser.mockReturnValue(new Promise(() => {}));

    render(<FollowButton userId={BALA.id} name="Bala" />);
    await user.click(await screen.findByRole("button", { name: /^follow bala$/i }));

    // The label has already changed with no round trip, which is the difference
    // between a button and a spinner.
    expect(await screen.findByText("Following")).toBeInTheDocument();
    expect(api.followUser).toHaveBeenCalledWith(BALA.id);
  });

  it("ignores a second tap while the first is still in flight", async () => {
    // Not "a double tap is harmless" -- two settled taps legitimately mean
    // unfollow then follow, and the reader asked for both. The bug worth
    // preventing is the *concurrent* one: two requests for one click, which
    // spends the endpoint twice and leaves the label disagreeing with the
    // server.
    const user = userEvent.setup();
    api.getFollowStatus.mockResolvedValue(status(true));
    api.unfollowUser.mockReturnValue(new Promise(() => {}));

    render(<FollowButton userId={BALA.id} name="Bala" />);

    const button = await screen.findByRole("button", { name: /following/i });
    await user.click(button);
    // The label has already flipped, so the second tap is on a disabled button.
    await user.click(await screen.findByRole("button", { name: /^follow bala$/i }));

    expect(api.unfollowUser).toHaveBeenCalledTimes(1);
    expect(api.followUser).not.toHaveBeenCalled();
  });

  it("unfollows once and settles on the server's answer", async () => {
    const user = userEvent.setup();
    api.getFollowStatus.mockResolvedValue(status(true));

    render(<FollowButton userId={BALA.id} name="Bala" />);
    await user.click(await screen.findByRole("button", { name: /following/i }));

    await waitFor(() =>
      expect(api.unfollowUser).toHaveBeenCalledWith(BALA.id),
    );
    expect(await screen.findByRole("button", { name: /^follow bala$/i })).toBeInTheDocument();
  });

  it("puts the button back and says why when the request fails", async () => {
    const user = userEvent.setup();
    api.followUser.mockRejectedValue(new Error("Too many attempts."));

    render(<FollowButton userId={BALA.id} name="Bala" />);
    await user.click(await screen.findByRole("button", { name: /^follow bala$/i }));

    // A button that silently snaps back with no explanation is the most
    // confusing failure there is, so the reason is on screen.
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts.");
    expect(screen.getByRole("button", { name: /^follow bala$/i })).toBeInTheDocument();
  });

  it("renders nothing for a signed-out reader", () => {
    // The endpoint needs an account, and a button that always fails when tapped
    // is worse than no button.
    authState.user = null;
    const { container } = render(<FollowButton userId={BALA.id} name="Bala" />);

    expect(container).toBeEmptyDOMElement();
    expect(api.getFollowStatus).not.toHaveBeenCalled();
  });

  it("renders nothing on your own review", () => {
    const { container } = render(<FollowButton userId={ME.id} name="Asha" />);

    expect(container).toBeEmptyDOMElement();
    expect(api.getFollowStatus).not.toHaveBeenCalled();
  });

  it("asks once per reviewer, not once per button", async () => {
    // This is the N+1, and the part of it that is worth asserting: three
    // reviews from two people is two requests, not three and not one.
    render(
      <>
        <FollowButton userId={BALA.id} name="Bala" />
        <FollowButton userId={DIVYA.id} name="Divya" />
        <FollowButton userId={BALA.id} name="Bala" />
      </>,
    );

    await waitFor(() => expect(screen.getAllByRole("button")).toHaveLength(3));
    await waitFor(() => expect(api.getFollowStatus).toHaveBeenCalledTimes(2));
    expect(api.getFollowStatus).toHaveBeenCalledWith(BALA.id);
    expect(api.getFollowStatus).toHaveBeenCalledWith(DIVYA.id);
  });

  it("does not re-ask after a click, because the click already knows the answer", async () => {
    const user = userEvent.setup();
    render(<FollowButton userId={BALA.id} name="Bala" />);
    await user.click(await screen.findByRole("button", { name: /^follow bala$/i }));

    expect(api.getFollowStatus).toHaveBeenCalledTimes(1);
    expect(api.followUser).toHaveBeenCalledTimes(1);
  });

  it("does not let a slow status lookup undo a click", async () => {
    // The race this component's cache exists to get right. A click that lands
    // while the lookup is still in flight has the newer answer; when the stale
    // response finally arrives it must not flip the button back.
    const user = userEvent.setup();
    let releaseStatus;
    api.getFollowStatus.mockReturnValue(
      new Promise((resolve) => {
        releaseStatus = resolve;
      }),
    );
    api.followUser.mockResolvedValue(status(true));

    render(<FollowButton userId={BALA.id} name="Bala" />);
    await user.click(await screen.findByRole("button", { name: /^follow bala$/i }));
    expect(await screen.findByRole("button", { name: /following/i })).toBeInTheDocument();

    // The lookup finally reports "not following", which was true a moment ago
    // and is now stale.
    releaseStatus(status(false));

    await waitFor(() => expect(api.getFollowStatus).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: /following/i })).toBeInTheDocument();
  });

  it("tells the parent when a follow settles, and when it fails", async () => {
    // The parent is what invalidates a "people I follow" list, so it has to hear
    // about the click immediately and about a failure that puts the state back.
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<FollowButton userId={BALA.id} name="Bala" onChange={onChange} />);

    await user.click(await screen.findByRole("button", { name: /^follow bala$/i }));
    expect(onChange).toHaveBeenCalledWith({ userId: BALA.id, isFollowing: true });

    onChange.mockClear();
    // The first click already flipped the label, so the retry is a follow again.
    api.followUser.mockRejectedValue(new Error("Too many attempts."));
    await user.click(await screen.findByRole("button", { name: /following/i }));

    // A failed follow has to be reported as well, or the list keeps someone the
    // reader is not actually following.
    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({ userId: BALA.id, isFollowing: false }),
    );
  });

  it("works with no onChange at all", async () => {
    // A reviewer list that does not filter still renders a button.
    const user = userEvent.setup();
    render(<FollowButton userId={BALA.id} name="Bala" />);

    await user.click(await screen.findByRole("button", { name: /^follow bala$/i }));

    expect(await screen.findByRole("button", { name: /following/i })).toBeInTheDocument();
  });

  it("stays usable when the status lookup fails", async () => {
    // The default state reads as "not following", which is the safe direction:
    // the worst case is a reader taps follow for someone they already follow,
    // and the endpoint is idempotent.
    const user = userEvent.setup();
    api.getFollowStatus.mockRejectedValue(new Error("offline"));

    render(<FollowButton userId={BALA.id} name="Bala" />);
    const button = await screen.findByRole("button", { name: /^follow bala$/i });

    expect(button).toBeInTheDocument();
    await user.click(button);
    expect(api.followUser).toHaveBeenCalledWith(BALA.id);
  });
});

// ---------- FriendsFeed ----------

describe("FriendsFeed", () => {
  it("empties the feed when you unfollow the last person in it", async () => {
    // The feed *is* the set of reviews by people you follow, so a follow change
    // has to invalidate it. Without this, unfollowing leaves the review on
    // screen until the reader navigates away and back -- which reads as the app
    // having ignored the click.
    const user = userEvent.setup();
    api.getFollowStatus.mockResolvedValue(status(true));
    api.getFollowingFeed
      .mockResolvedValueOnce({ entries: [review(1, BALA, "From Bala.")], count: 1 })
      .mockResolvedValue({ entries: [], count: 0 });
    api.listMyFollowing
      .mockResolvedValueOnce({ users: [BALA], count: 1 })
      .mockResolvedValue({ users: [], count: 0 });

    render(<FriendsFeed />);
    await screen.findByText("From Bala.");

    await user.click(await screen.findByTestId(`follow-${BALA.id}`));

    await waitFor(() => expect(screen.queryByText("From Bala.")).not.toBeInTheDocument());
    expect(api.getFollowingFeed).toHaveBeenCalledTimes(2);
    expect(
      await screen.findByText(/you are not following anyone yet/i),
    ).toBeInTheDocument();
  });

  it("refreshes the people list after an unfollow, not just the feed", async () => {
    const user = userEvent.setup();
    api.getFollowStatus.mockResolvedValue(status(true));
    api.getFollowingFeed.mockResolvedValue({ entries: [], count: 0 });
    api.listMyFollowing
      .mockResolvedValueOnce({ users: [BALA, DIVYA], count: 2 })
      .mockResolvedValue({ users: [DIVYA], count: 1 });

    render(<FriendsFeed />);
    await screen.findByTestId(`follow-${BALA.id}`);

    await user.click(screen.getByTestId(`follow-${BALA.id}`));

    // The empty state explains who you follow, so a stale count there is a
    // different wrong answer from a stale feed.
    await waitFor(() => expect(api.listMyFollowing).toHaveBeenCalledTimes(2));
  });

  it("renders each review with who wrote it and where", async () => {
    api.getFollowingFeed.mockResolvedValue({
      entries: [review(1, BALA, "The dosa is worth the walk.")],
      count: 1,
    });

    render(<FriendsFeed />);

    expect(
      await screen.findByText("The dosa is worth the walk."),
    ).toBeInTheDocument();
    // The author is named, and the follow button says whose it is rather than
    // being one of several buttons all called "Follow".
    expect(
      screen.getByRole("button", { name: /^follow bala$/i }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Corner House/ })).toBeInTheDocument();
  });

  it("says how to fix it when you follow nobody", async () => {
    // "No reviews" on its own leaves a reader thinking the feature is broken.
    api.getFollowingFeed.mockResolvedValue({ entries: [], count: 0 });
    api.listMyFollowing.mockResolvedValue({ users: [], count: 0 });

    render(<FriendsFeed />);

    expect(
      await screen.findByText(/you are not following anyone yet/i),
    ).toBeInTheDocument();
  });

  it("distinguishes following-nobody from following-people-who-are-quiet", async () => {
    api.getFollowingFeed.mockResolvedValue({ entries: [], count: 0 });
    api.listMyFollowing.mockResolvedValue({ users: [BALA, DIVYA], count: 2 });

    render(<FriendsFeed />);

    expect(await screen.findByText(/you follow 2 people/i)).toBeInTheDocument();
    // And it is useful rather than merely explanatory: the people are listed,
    // each with the button to stop following them. Queried by the list item
    // rather than by text, because the button's accessible name repeats the
    // name and a bare getByText finds both.
    const items = screen.getAllByRole("listitem");
    expect(items.map((item) => item.firstChild.textContent)).toEqual([
      "Bala",
      "Divya",
    ]);
    expect(screen.getByTestId(`follow-${BALA.id}`)).toBeInTheDocument();
  });

  it("keeps the two empty reasons apart when there is exactly one person", async () => {
    api.listMyFollowing.mockResolvedValue({ users: [BALA], count: 1 });

    render(<FriendsFeed />);

    expect(await screen.findByText(/you follow 1 person,/i)).toBeInTheDocument();
  });

  it("tells a signed-out reader to sign in", async () => {
    authState.user = null;

    render(<FriendsFeed />);

    expect(await screen.findByText(/sign in to see reviews/i)).toBeInTheDocument();
    expect(api.getFollowingFeed).not.toHaveBeenCalled();
  });

  it("shows the server's reason when the feed cannot be loaded", async () => {
    api.getFollowingFeed.mockRejectedValue(new Error("Invalid or expired token"));

    render(<FriendsFeed />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid or expired token",
    );
  });

  it("opens the place a review was written about", async () => {
    const onOpenRestaurant = vi.fn();
    api.getFollowingFeed.mockResolvedValue({
      entries: [review(1, BALA, "Worth it.")],
      count: 1,
    });

    render(<FriendsFeed onOpenRestaurant={onOpenRestaurant} />);
    await userEvent.click(await screen.findByRole("button", { name: /Corner House/ }));

    expect(onOpenRestaurant).toHaveBeenCalledWith(10);
  });

  it("does not fetch while the session is still being restored", async () => {
    // Otherwise a reload fires an authenticated request with a token that has
    // not been read from storage yet, and gets a 401 for a reader who is signed
    // in perfectly well.
    authState.user = null;
    authState.loading = true;

    render(<FriendsFeed />);

    expect(api.getFollowingFeed).not.toHaveBeenCalled();
    expect(api.listMyFollowing).not.toHaveBeenCalled();
  });

  it("carries a follow button on each review's author", async () => {
    api.getFollowingFeed.mockResolvedValue({
      entries: [review(1, BALA, "One."), review(2, DIVYA, "Two.")],
      count: 2,
    });

    render(<FriendsFeed />);

    await waitFor(() => expect(screen.getByText("Two.")).toBeInTheDocument());
    expect(screen.getByTestId(`follow-${BALA.id}`)).toBeInTheDocument();
    expect(screen.getByTestId(`follow-${DIVYA.id}`)).toBeInTheDocument();
    // And not on your own, which cannot happen here but is handled anyway.
    expect(screen.queryByTestId(`follow-${ME.id}`)).not.toBeInTheDocument();
  });
});
