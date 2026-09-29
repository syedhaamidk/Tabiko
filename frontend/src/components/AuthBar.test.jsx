/**
 * The auth bar with Google blended in.
 *
 * The failure this file exists for is visible in one glance: the Google
 * button stranded on its own row beneath Log in / Sign up, reading as an
 * afterthought rather than a way in. These tests assert the row holds all
 * three, in both the guest view and the form views, and that a disabled
 * provider leaves no divider dangling behind.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getAuthProviders: vi.fn(),
}));

const authState = vi.hoisted(() => ({
  user: null,
  login: vi.fn(),
  register: vi.fn(),
  loginWithGoogle: vi.fn(),
  logout: vi.fn(),
}));

vi.mock("../api", () => api);

vi.mock("../AuthContext", () => ({
  useAuth: () => authState,
}));

import AuthBar from "./AuthBar";
import { _resetGisForTests } from "./GoogleSignIn";

const ENABLED = {
  google_enabled: true,
  google_client_id: "test.apps.googleusercontent.com",
};

function fakeGis() {
  const initialize = vi.fn();
  const renderButton = vi.fn();
  Object.defineProperty(window, "google", {
    value: { accounts: { id: { initialize, renderButton } } },
    configurable: true,
    writable: true,
  });
  return { initialize, renderButton };
}

beforeEach(() => {
  _resetGisForTests();
  delete window.google;
  authState.user = null;
  authState.loginWithGoogle.mockResolvedValue(undefined);
  api.getAuthProviders.mockResolvedValue(ENABLED);
});

afterEach(() => {
  vi.clearAllMocks();
  delete window.google;
});

describe("AuthBar with Google", () => {
  it("holds email buttons, divider and Google slot in one actions row", async () => {
    fakeGis();
    const { container } = render(<AuthBar />);

    const actions = container.querySelector(".auth-bar__actions");
    expect(actions).not.toBeNull();
    const scoped = within(actions);
    expect(scoped.getByRole("button", { name: "Log in" })).toBeInTheDocument();
    expect(scoped.getByRole("button", { name: /sign up free/i })).toBeInTheDocument();
    // The divider arrives with the providers answer, not with the first paint.
    await waitFor(() => scoped.getByTestId("google-button-slot"));
    expect(scoped.getByText("or")).toBeInTheDocument();
  });

  it("shows no divider and no slot when Google is not configured", async () => {
    api.getAuthProviders.mockResolvedValue({
      google_enabled: false,
      google_client_id: null,
    });
    const { container } = render(<AuthBar />);

    await waitFor(() => expect(api.getAuthProviders).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(container.querySelector(".auth-divider")).toBeNull();
    expect(container.querySelector('[data-testid="google-button-slot"]')).toBeNull();
    // The email buttons are unaffected: the bar degrades to exactly what it
    // was before Google existed.
    expect(screen.getByRole("button", { name: "Log in" })).toBeInTheDocument();
  });

  it("carries the divider and the slot into the login form", async () => {
    fakeGis();
    const user = userEvent.setup();
    render(<AuthBar />);

    await user.click(screen.getByRole("button", { name: "Log in" }));

    const form = document.querySelector("form.auth-bar--form");
    expect(form).not.toBeNull();
    const scoped = within(form);
    expect(scoped.getByText("or")).toBeInTheDocument();
    expect(scoped.getByTestId("google-button-slot")).toBeInTheDocument();
  });

  it("closes the form after a Google sign-in", async () => {
    const { initialize } = fakeGis();
    const user = userEvent.setup();
    render(<AuthBar />);
    await user.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() => expect(initialize).toHaveBeenCalled());
    await initialize.mock.calls[0][0].callback({ credential: "good-token" });

    // The form is gone and the guest bar is back: a successful sign-in looks
    // the same whichever door the reader came through.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Log in" })).toBeInTheDocument(),
    );
  });
});
