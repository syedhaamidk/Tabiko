import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RestaurantDetail from "./RestaurantDetail";

/**
 * Filling in a menu one dish per form submission is why nobody fills one in, so
 * the bulk path is the feature. What matters here is that the empty state
 * invites a contribution, that a paste lands, and that a partially-duplicate
 * paste reports both halves rather than appearing to have done nothing.
 */

vi.mock("../api", () => ({
  getRestaurant: vi.fn(),
  listDishes: vi.fn(),
  getRestaurantReviews: vi.fn(),
  // FollowButton renders inside every review, so these are reached as soon as a
  // review list has an author in it. Absent exports fail as unhandled rejections
  // rather than test failures, which is a miserable way to find out.
  getFollowStatus: vi.fn(),
  followUser: vi.fn(),
  unfollowUser: vi.fn(),
  addDish: vi.fn(),
  addDishesBulk: vi.fn(),
  createReview: vi.fn(),
  confirmMenu: vi.fn(),
}));

/*
 * These have to be stable identities. The detail panel refetches whenever
 * applyThemeForRestaurant changes, so a mock that hands back a fresh vi.fn() on
 * every render would loop the load effect and no response would ever land.
 */
const themeSpy = { applyThemeForRestaurant: vi.fn(), resetTheme: vi.fn() };
vi.mock("../ThemeContext", () => ({ useTheme: () => themeSpy }));
vi.mock("../AuthContext", () => ({ useAuth: vi.fn() }));

import {
  addDish,
  addDishesBulk,
  confirmMenu,
  getRestaurant,
  getRestaurantReviews,
  listDishes,
  getFollowStatus,
  followUser,
  unfollowUser,
} from "../api";
import { useAuth } from "../AuthContext";

const PLACE = {
  id: 7,
  name: "Toit",
  address: "Richmond Road",
  cuisine_tags: "Multi-cuisine, Beer Bar",
  type_tag: "family_restaurant",
  price_tier: 2,
  menu_last_confirmed: null,
};

const dish = (id, name, addedBy = null) => ({
  id,
  restaurant_id: 7,
  name,
  tags: null,
  avg_rating: 0,
  review_count: 0,
  added_by: addedBy,
});

const READER = { id: 1, name: "Asha", is_critic_verified: false };
const CRITIC = { id: 2, name: "Rahul", is_critic_verified: true };

/**
 * Defaults for the follow calls FollowButton makes.
 *
 * Set at the top level rather than per describe, because FollowButton renders
 * inside every review and an unstubbed `getFollowStatus` returns undefined --
 * which fails as an unhandled rejection somewhere else entirely, not as a
 * failure of the test that caused it.
 */
beforeEach(() => {
  getFollowStatus.mockResolvedValue({
    is_following: false,
    follower_count: 0,
    following_count: 0,
  });
  followUser.mockResolvedValue({
    is_following: true,
    follower_count: 1,
    following_count: 1,
  });
  unfollowUser.mockResolvedValue({
    is_following: false,
    follower_count: 0,
    following_count: 0,
  });
  // Some describes assert the unfiltered request, so the default has to say so.
  getFollowStatus.mockResolvedValue({
    is_following: false,
    follower_count: 0,
    following_count: 0,
  });
});

async function renderDetail() {
  const result = render(<RestaurantDetail restaurantId={7} onBack={vi.fn()} />);
  await screen.findByRole("heading", { name: "Toit" });
  return result;
}

describe("narrowing the reviews to people you follow", () => {
  const reviewFrom = (id, name) => ({
    id,
    user_id: name === "Asha" ? READER.id : 2,
    restaurant_id: 7,
    dish_id: null,
    rating: 5,
    text: `From ${name}`,
    verification_tier: "unverified",
    fraud_flag: false,
    created_at: "2026-01-01T12:00:00Z",
    image_url: null,
    reviewer: {
      id: name === "Asha" ? READER.id : 2,
      name,
      reviewer_type: "normal",
      is_critic_verified: false,
      cuisine_specialty: null,
      is_regular_here: false,
    },
  });

  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ user: READER });
    getRestaurant.mockResolvedValue(PLACE);
    listDishes.mockResolvedValue([]);
  });

  it("asks the server for the filtered list rather than hiding rows locally", async () => {
    getRestaurantReviews.mockResolvedValue([reviewFrom(1, "Asha"), reviewFrom(2, "Rahul")]);
    await renderDetail();
    expect(screen.getByText("From Asha")).toBeInTheDocument();

    getRestaurantReviews.mockResolvedValue([reviewFrom(2, "Rahul")]);
    await userEvent.click(screen.getByTestId("following-only"));

    await screen.findByText("From Rahul");
    expect(screen.queryByText("From Asha")).not.toBeInTheDocument();

    // The filter is a server-side question, and the server is the only thing
    // that knows who the viewer follows. Filtering an already-fetched list would
    // send reviews a reader is not allowed to see and hide them silently.
    expect(getRestaurantReviews).toHaveBeenLastCalledWith(7, { followingOnly: true });
    expect(getRestaurantReviews).toHaveBeenNthCalledWith(1, 7, { followingOnly: false });
  });

  it("explains an empty filtered list instead of shrugging", async () => {
    getRestaurantReviews.mockResolvedValue([reviewFrom(1, "Asha")]);
    await renderDetail();

    getRestaurantReviews.mockResolvedValue([]);
    await userEvent.click(screen.getByTestId("following-only"));

    expect(
      await screen.findByText(/nobody you follow has reviewed this place yet/i),
    ).toBeInTheDocument();
    // And not the first-run wording, which would be a different claim.
    expect(screen.queryByText(/be the first neighbor/i)).not.toBeInTheDocument();
  });

  it("surfaces the server's reason rather than showing an empty list", async () => {
    getRestaurantReviews.mockResolvedValue([reviewFrom(1, "Asha")]);
    await renderDetail();

    getRestaurantReviews.mockRejectedValue(
      new Error("Sign in to see reviews from people you follow."),
    );
    await userEvent.click(screen.getByTestId("following-only"));

    // A 401 here would otherwise look exactly like "you follow nobody", and the
    // reader would have no way to tell the two apart.
    expect(await screen.findByRole("alert")).toHaveTextContent(/sign in/i);
  });

  it("drops a review from the filtered list when you unfollow its author", async () => {
    // The filtered list is derived from who the reader follows, so a follow
    // change has to invalidate it. Otherwise unfollowing leaves the review on
    // screen until the reader navigates away and back, which reads as the app
    // having ignored the click.
    getRestaurantReviews.mockResolvedValue([reviewFrom(2, "Rahul")]);
    await renderDetail();

    await userEvent.click(screen.getByTestId("following-only"));
    await screen.findByText("From Rahul");

    // The server, having been told, now returns nothing for this viewer.
    getRestaurantReviews.mockResolvedValue([]);
    await userEvent.click(await screen.findByTestId("follow-2"));

    expect(
      await screen.findByText(/nobody you follow has reviewed this place yet/i),
    ).toBeInTheDocument();
  });

  it("offers no filter to a signed-out reader", async () => {
    useAuth.mockReturnValue({ user: null });
    getRestaurantReviews.mockResolvedValue([reviewFrom(2, "Rahul")]);

    await renderDetail();

    // The endpoint needs an account, and a control that always 401s is worse
    // than no control.
    expect(screen.queryByTestId("following-only")).not.toBeInTheDocument();
  });
});

describe("the empty menu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ user: READER });
    getRestaurant.mockResolvedValue(PLACE);
    listDishes.mockResolvedValue([]);
    getRestaurantReviews.mockResolvedValue([]);
  });

  it("asks a signed-in reader to fill it in rather than shrugging", async () => {
    await renderDetail();

    expect(screen.getByText(/nobody has written this menu down yet/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add the menu/i })).toBeInTheDocument();
  });

  it("tells a signed-out reader why they cannot add anything", async () => {
    useAuth.mockReturnValue({ user: null });

    await renderDetail();

    expect(screen.getByText(/log in and add what they serve/i)).toBeInTheDocument();
    // Nothing to click into, so no dead button.
    expect(screen.queryByRole("button", { name: /add the menu/i })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/dish name/i)).not.toBeInTheDocument();
  });

  it("opens the paste box straight from the invitation", async () => {
    const user = userEvent.setup();
    await renderDetail();

    await user.click(screen.getByRole("button", { name: /add the menu/i }));

    expect(screen.getByLabelText(/paste the menu/i)).toBeInTheDocument();
  });
});

describe("adding a whole menu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ user: READER });
    getRestaurant.mockResolvedValue(PLACE);
    listDishes.mockResolvedValue([]);
    getRestaurantReviews.mockResolvedValue([]);
  });

  it("sends the pasted text and shows the dishes that landed", async () => {
    const user = userEvent.setup();
    addDishesBulk.mockResolvedValue({
      added: [dish(1, "Masala Dosa"), dish(2, "Filter Coffee")],
      skipped: [],
    });
    await renderDetail();
    await user.click(screen.getByRole("button", { name: /add the menu/i }));

    await user.type(screen.getByLabelText(/paste the menu/i), "Masala Dosa");
    await user.click(screen.getByRole("button", { name: /add them all/i }));

    await waitFor(() => expect(addDishesBulk).toHaveBeenCalledWith(7, "Masala Dosa"));
    expect(await screen.findByText("Added 2 dishes.")).toBeInTheDocument();
    // The dishes are on screen immediately, not only after a refetch.
    expect(screen.getByRole("heading", { name: "Masala Dosa" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Filter Coffee" })).toBeInTheDocument();
  });

  it("reports the dishes it skipped instead of quietly dropping them", async () => {
    const user = userEvent.setup();
    addDishesBulk.mockResolvedValue({
      added: [dish(3, "Idli")],
      skipped: ["Masala Dosa"],
    });
    await renderDetail();
    await user.click(screen.getByRole("button", { name: /add the menu/i }));

    await user.type(screen.getByLabelText(/paste the menu/i), "Idli");
    await user.click(screen.getByRole("button", { name: /add them all/i }));

    const result = await screen.findByRole("status");
    expect(result).toHaveTextContent("Added 1 dish.");
    // "Idli" alone: the singular reads as a bug otherwise.
    expect(result).toHaveTextContent("Already on the menu: Masala Dosa.");
  });

  it("says so plainly when a paste was entirely duplicates", async () => {
    const user = userEvent.setup();
    addDishesBulk.mockResolvedValue({ added: [], skipped: ["Masala Dosa"] });
    await renderDetail();
    await user.click(screen.getByRole("button", { name: /add the menu/i }));

    await user.type(screen.getByLabelText(/paste the menu/i), "Masala Dosa");
    await user.click(screen.getByRole("button", { name: /add them all/i }));

    expect(await screen.findByText(/nothing new to add/i)).toBeInTheDocument();
  });

  it("will not submit an empty box", async () => {
    const user = userEvent.setup();
    await renderDetail();
    await user.click(screen.getByRole("button", { name: /add the menu/i }));

    expect(screen.getByRole("button", { name: /add them all/i })).toBeDisabled();

    await user.type(screen.getByLabelText(/paste the menu/i), "Masala Dosa");
    expect(screen.getByRole("button", { name: /add them all/i })).toBeEnabled();
  });

  it("surfaces a refusal from the server instead of claiming success", async () => {
    const user = userEvent.setup();
    addDishesBulk.mockRejectedValue(new Error("That dish is already on the menu"));
    await renderDetail();
    await user.click(screen.getByRole("button", { name: /add the menu/i }));

    await user.type(screen.getByLabelText(/paste the menu/i), "Masala Dosa");
    await user.click(screen.getByRole("button", { name: /add them all/i }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/already on the menu/i);
  });

  it("stays open so a failed paste is not lost", async () => {
    const user = userEvent.setup();
    addDishesBulk.mockRejectedValue(new Error("nope"));
    await renderDetail();
    await user.click(screen.getByRole("button", { name: /add the menu/i }));

    await user.type(screen.getByLabelText(/paste the menu/i), "Masala Dosa");
    await user.click(screen.getByRole("button", { name: /add them all/i }));

    // Twenty lines of transcription should not vanish because of one bad request.
    await waitFor(() =>
      expect(screen.getByLabelText(/paste the menu/i)).toHaveValue("Masala Dosa"),
    );
  });
});

describe("crediting the contributor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ user: READER });
    getRestaurant.mockResolvedValue(PLACE);
    getRestaurantReviews.mockResolvedValue([]);
  });

  it("names whoever added a dish", async () => {
    listDishes.mockResolvedValue([dish(1, "Masala Dosa", READER)]);

    await renderDetail();

    expect(screen.getByText("Added by Asha")).toBeInTheDocument();
  });

  it("marks a menu the project already vouches for", async () => {
    listDishes.mockResolvedValue([dish(1, "Masala Dosa", CRITIC)]);

    await renderDetail();

    expect(screen.getByText("Added by Rahul · verified critic")).toBeInTheDocument();
  });

  it("says nothing about the source of a dish with no contributor", async () => {
    listDishes.mockResolvedValue([dish(1, "Masala Dosa", null)]);

    await renderDetail();

    expect(screen.getByRole("heading", { name: "Masala Dosa" })).toBeInTheDocument();
    // "Added by nobody" is a worse lie than silence.
    expect(screen.queryByText(/added by/i)).not.toBeInTheDocument();
  });
});

describe("a place that already has a menu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ user: READER });
    getRestaurant.mockResolvedValue(PLACE);
    getRestaurantReviews.mockResolvedValue([]);
    listDishes.mockResolvedValue([dish(1, "Masala Dosa", READER)]);
  });

  it("tucks bulk entry behind a toggle rather than shouting over the menu", async () => {
    await renderDetail();

    expect(screen.getByRole("heading", { name: "Masala Dosa" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/paste the menu/i)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /add a whole menu/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("still offers the single-dish form", async () => {
    await renderDetail();

    expect(screen.getByLabelText("Dish name")).toBeInTheDocument();
  });

  it("closes the box again and drops the previous result", async () => {
    const user = userEvent.setup();
    addDishesBulk.mockResolvedValue({ added: [dish(9, "Idli")], skipped: [] });
    await renderDetail();

    await user.click(screen.getByRole("button", { name: /add a whole menu/i }));
    await user.type(screen.getByLabelText(/paste the menu/i), "Idli");
    await user.click(screen.getByRole("button", { name: /add them all/i }));
    expect(await screen.findByText("Added 1 dish.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(screen.queryByLabelText(/paste the menu/i)).not.toBeInTheDocument();
    // A stale count sitting under a closed box would misreport the menu.
    expect(screen.queryByText("Added 1 dish.")).not.toBeInTheDocument();
  });
});

describe("the single-dish form still works", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ user: READER });
    getRestaurant.mockResolvedValue(PLACE);
    getRestaurantReviews.mockResolvedValue([]);
    listDishes.mockResolvedValue([]);
  });

  it("adds one dish and credits the reader", async () => {
    const user = userEvent.setup();
    addDish.mockResolvedValue(dish(1, "Idli", READER));
    await renderDetail();

    await user.type(screen.getByLabelText("Dish name"), "Idli");
    await user.click(screen.getByRole("button", { name: /^add dish$/i }));

    await waitFor(() => expect(addDish).toHaveBeenCalledWith(7, "Idli", ""));
    expect(await screen.findByText("Added by Asha")).toBeInTheDocument();
  });

  it("will not submit a blank dish", async () => {
    const user = userEvent.setup();
    await renderDetail();

    await user.click(screen.getByRole("button", { name: /^add dish$/i }));

    expect(addDish).not.toHaveBeenCalled();
  });
});

describe("vouching for a menu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuth.mockReturnValue({ user: READER });
    getRestaurantReviews.mockResolvedValue([]);
    listDishes.mockResolvedValue([dish(1, "Masala Dosa", READER)]);
  });

  it("re-reads the place so a stale claim is not left on screen", async () => {
    const user = userEvent.setup();
    getRestaurant.mockResolvedValue(PLACE);
    confirmMenu.mockResolvedValue({ ...PLACE, menu_last_confirmed: "2026-09-01T00:00:00" });
    await renderDetail();

    await user.click(screen.getByRole("button", { name: /i vouch for this menu/i }));

    expect(await screen.findByText("Freshly confirmed")).toBeInTheDocument();
  });

  it("drops the freshness claim when a dish is added afterwards", async () => {
    const user = userEvent.setup();
    // Fresh on load, then stale the moment a dish is added, which is what the
    // backend now reports.
    getRestaurant
      .mockResolvedValueOnce({ ...PLACE, menu_last_confirmed: "2026-09-01T00:00:00" })
      .mockResolvedValue(PLACE);
    addDishesBulk.mockResolvedValue({ added: [dish(2, "Idli", READER)], skipped: [] });
    await renderDetail();
    expect(await screen.findByText("Freshly confirmed")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /add a whole menu/i }));
    await user.type(screen.getByLabelText(/paste the menu/i), "Idli");
    await user.click(screen.getByRole("button", { name: /add them all/i }));

    // A menu that just changed must not keep claiming to be freshly confirmed,
    // so the panel re-reads the place rather than trusting what it had.
    expect(await screen.findByText("Flavor check needed")).toBeInTheDocument();
  });
});
