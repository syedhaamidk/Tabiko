/**
 * The install button: when it appears, what it fires, and when it stays out
 * of the way.
 *
 * The browser's own prompt is never touched here beyond a mock: what is
 * owned is the state machine around it. The three ways this goes wrong in
 * production are a button for an installed app, a button that returns after
 * being dismissed, and a dead button on iOS — one test for each.
 */

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import InstallButton from "./InstallButton";

const DISMISS_KEY = "tabiko-install-dismissed";

function fireInstallPrompt(outcome = "accepted") {
  const event = new Event("beforeinstallprompt");
  event.prompt = vi.fn();
  Object.defineProperty(event, "userChoice", {
    value: Promise.resolve({ outcome }),
  });
  window.dispatchEvent(event);
  return event;
}

function setStandalone(matches) {
  window.matchMedia = vi.fn(() => ({
    matches,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
}

const IPHONE_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15";

function setUserAgent(value) {
  Object.defineProperty(window.navigator, "userAgent", {
    value,
    configurable: true,
  });
}

const DESKTOP_UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36";

beforeEach(() => {
  localStorage.clear();
  setStandalone(false);
  setUserAgent(DESKTOP_UA);
  delete window.navigator.standalone;
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("InstallButton", () => {
  it("renders nothing before the browser offers installation", () => {
    const { container } = render(<InstallButton />);

    expect(container).toBeEmptyDOMElement();
  });

  it("appears when the browser offers, and fires the held prompt", async () => {
    const user = userEvent.setup();
    render(<InstallButton />);
    const event = fireInstallPrompt("accepted");

    const button = await screen.findByRole("button", {
      name: /take tabiko to go/i,
    });
    await user.click(button);

    expect(event.prompt).toHaveBeenCalledTimes(1);
    // Accepted: the app is on its way in, so the button leaves.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /take tabiko to go/i })).not.toBeInTheDocument(),
    );
  });

  it("snoozes when the native prompt is declined", async () => {
    const user = userEvent.setup();
    render(<InstallButton />);
    fireInstallPrompt("dismissed");

    await user.click(
      await screen.findByRole("button", { name: /take tabiko to go/i }),
    );

    // Declining the native prompt is a dismissal with extra steps: the
    // button goes away and the timestamp says when.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /take tabiko to go/i })).not.toBeInTheDocument(),
    );
    expect(Number(localStorage.getItem(DISMISS_KEY))).toBeGreaterThan(0);
  });

  it("stays away after being dismissed, and returns after thirty days", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<InstallButton />);
    fireInstallPrompt();

    await user.click(await screen.findByRole("button", { name: /not now/i }));
    expect(
      screen.queryByRole("button", { name: /take tabiko to go/i }),
    ).not.toBeInTheDocument();
    unmount();

    // A dismissal that returns tomorrow teaches readers that dismissing does
    // nothing; one that never returns loses the affordance forever.
    const second = render(<InstallButton />);
    expect(second.container).toBeEmptyDOMElement();
    second.unmount();

    localStorage.setItem(
      DISMISS_KEY,
      String(Date.now() - 31 * 86400000),
    );
    render(<InstallButton />);
    fireInstallPrompt();
    expect(
      await screen.findByRole("button", { name: /take tabiko to go/i }),
    ).toBeInTheDocument();
  });

  it("renders nothing for an installed app", () => {
    // Installed, but the browser fires the event anyway (it happens): the
    // installed check wins, because a button for an installed app is the
    // most embarrassing button there is.
    setStandalone(true);
    fireInstallPrompt();
    const { container } = render(<InstallButton />);

    expect(container).toBeEmptyDOMElement();
  });

  it("spells out the manual steps on iOS, where no event ever fires", async () => {
    const user = userEvent.setup();
    setUserAgent(IPHONE_UA);
    render(<InstallButton />);

    await user.click(
      await screen.findByRole("button", { name: /take tabiko to go/i }),
    );

    expect(await screen.findByText(/add to home screen/i)).toBeInTheDocument();
  });

  it("renders nothing on an installed iPhone", () => {
    setUserAgent(IPHONE_UA);
    Object.defineProperty(window.navigator, "standalone", {
      value: true,
      configurable: true,
    });
    const { container } = render(<InstallButton />);

    expect(container).toBeEmptyDOMElement();
  });
});
