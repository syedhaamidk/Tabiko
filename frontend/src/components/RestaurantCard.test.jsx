import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RestaurantCard, { formatDistance } from "./RestaurantCard";
import { LOCATION_STATUS } from "../lib/useUserLocation";

/**
 * The card is where distance, saving and the "explore" action all live, and it
 * has to stay a single button with a sibling save control: nesting a button
 * inside the card's own button is invalid and would strand keyboard readers.
 */

const PLACE = {
  id: 42,
  name: "Hotel Kaveri",
  latitude: 12.9915,
  longitude: 77.552,
  cuisine_tags: "Multi-cuisine, South Indian",
  type_tag: "family_restaurant",
  good_for: "outdoor, quick_bite",
  dietary_flags: "veg",
  noise_level: "quiet",
};

describe("formatDistance", () => {
  it("rounds metres below a kilometre to the nearest ten", () => {
    expect(formatDistance(0)).toBe("0 m");
    expect(formatDistance(189.14)).toBe("190 m");
    expect(formatDistance(944.9)).toBe("940 m");
  });

  it("switches to kilometres with one decimal above 950 m", () => {
    expect(formatDistance(950)).toBe("1.0 km");
    expect(formatDistance(1049)).toBe("1.0 km");
    expect(formatDistance(10490)).toBe("10.5 km");
  });

  it("returns nothing when the request carried no origin", () => {
    // Absent is not zero: showing "0 m" would be a claim we cannot back.
    expect(formatDistance(null)).toBeNull();
    expect(formatDistance(undefined)).toBeNull();
  });
});

describe("RestaurantCard", () => {
  let onSelect;
  let onToggleSave;

  const renderCard = (props = {}) => {
    onSelect = vi.fn();
    onToggleSave = vi.fn();
    return render(
      <RestaurantCard
        restaurant={PLACE}
        onSelect={onSelect}
        onToggleSave={onToggleSave}
        {...props}
      />,
    );
  };

  beforeEach(() => {
    onSelect = vi.fn();
    onToggleSave = vi.fn();
  });

  it("shows a distance only when the request supplied one", () => {
    const { container, rerender } = renderCard();
    expect(container.querySelector(".distance-badge")).not.toBeInTheDocument();

    rerender(
      <RestaurantCard
        restaurant={{ ...PLACE, distance_m: 189.1 }}
        onSelect={onSelect}
        onToggleSave={onToggleSave}
      />,
    );
    expect(screen.getByText("190 m")).toBeInTheDocument();
  });

  it("opens the place without saving it", async () => {
    const user = userEvent.setup();
    renderCard();

    await user.click(screen.getByRole("button", { name: /explore/i }));

    expect(onSelect).toHaveBeenCalledWith(42);
    expect(onToggleSave).not.toHaveBeenCalled();
  });

  it("saves without opening the place", async () => {
    const user = userEvent.setup();
    renderCard();

    await user.click(screen.getByRole("button", { name: /save hotel kaveri/i }));

    expect(onToggleSave).toHaveBeenCalledWith(42);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("offers the remove affordance once a place is saved", () => {
    renderCard({ saved: true });
    expect(
      screen.getByRole("button", { name: /remove hotel kaveri from saved/i }),
    ).toBeInTheDocument();
  });

  it("is reachable by keyboard and reports its pressed state", async () => {
    const user = userEvent.setup();
    renderCard();

    const button = screen.getByRole("button", { name: /save hotel kaveri/i });
    expect(button).toHaveAttribute("aria-pressed", "false");

    // The card's own button comes first in the DOM, so this focuses the save
    // control directly rather than assuming a tab order.
    button.focus();
    expect(button).toHaveFocus();
    await user.keyboard("{Enter}");

    expect(onToggleSave).toHaveBeenCalledWith(42);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("puts the save control after the card in the tab order", async () => {
    // Nesting the save button inside the card's button would make the card
    // untabbable in some browsers, so the two are siblings by construction and
    // the card comes first.
    const user = userEvent.setup();
    const { container } = renderCard();

    const buttons = container.querySelectorAll("button");
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveClass("restaurant-card");
    expect(buttons[1]).toHaveClass("save-toggle");

    await user.tab();
    expect(buttons[0]).toHaveFocus();
    await user.tab();
    expect(buttons[1]).toHaveFocus();
  });

  it("does not render a save control when saving is not offered", () => {
    render(
      <RestaurantCard restaurant={PLACE} onSelect={onSelect} />,
    );
    expect(screen.queryByRole("button", { name: /^save/i })).not.toBeInTheDocument();
  });

  it("keeps the save control from firing twice while a save is in flight", () => {
    renderCard({ saving: true });
    expect(screen.getByRole("button", { name: /save hotel kaveri/i })).toBeDisabled();
  });

  it("tolerates a place with no tags at all", () => {
    render(
      <RestaurantCard
        restaurant={{ id: 1, name: "Bare", latitude: 12, longitude: 77 }}
        onSelect={onSelect}
      />,
    );
    expect(screen.getByText("Bare")).toBeInTheDocument();
  });
});

describe("LocationGate", () => {
  // Imported here rather than above so the module boundary is obvious.
  it("keeps cards hidden until permission is granted", async () => {
    const { default: LocationGate } = await import("./LocationGate");

    render(
      <LocationGate status={LOCATION_STATUS.prompt}>
        <p>the cards</p>
      </LocationGate>,
    );

    expect(screen.queryByText("the cards")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /turn on location/i })).toBeInTheDocument();
  });

  it("shows the cards once permission is granted", async () => {
    const { default: LocationGate } = await import("./LocationGate");

    render(
      <LocationGate status={LOCATION_STATUS.granted}>
        <p>the cards</p>
      </LocationGate>,
    );

    expect(screen.getByText("the cards")).toBeInTheDocument();
  });

  it("offers the map instead when location will not be shared", async () => {
    const { default: LocationGate } = await import("./LocationGate");
    const onBrowseMap = vi.fn();
    const user = userEvent.setup();

    render(
      <LocationGate status={LOCATION_STATUS.unavailable} onBrowseMap={onBrowseMap}>
        <p>the cards</p>
      </LocationGate>,
    );

    // A browser that cannot share a location must not offer a button that
    // cannot work.
    expect(screen.queryByRole("button", { name: /turn on location/i })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /food map instead/i }));
    expect(onBrowseMap).toHaveBeenCalled();
  });

  it("waits rather than guessing while the permission is being read", async () => {
    const { default: LocationGate } = await import("./LocationGate");

    const { container } = render(
      <LocationGate status={LOCATION_STATUS.checking}>
        <p>the cards</p>
      </LocationGate>,
    );

    expect(container.querySelector(".location-gate")).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText("the cards")).not.toBeInTheDocument();
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("test hygiene", () => {
  it("has a real user-event implementation", async () => {
    // Guards against a silent no-op that would make every interaction test lie.
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<button onClick={onClick}>press</button>);
    await act(async () => {
      await user.click(screen.getByRole("button", { name: "press" }));
    });
    await waitFor(() => expect(onClick).toHaveBeenCalled());
  });
});
