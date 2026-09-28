/**
 * The Google sign-in button.
 *
 * Google's own script is never loaded here. What is tested is everything
 * around it that this project owns: when the button appears at all, what a
 * missing script or a refused login looks like, and that the credential goes
 * exactly one place. The button pixels belong to Google.
 */

import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getAuthProviders: vi.fn(),
  loginWithGoogle: vi.fn(),
}));

const authState = vi.hoisted(() => ({
  loginWithGoogle: vi.fn(),
  user: null,
}));

vi.mock("../api", () => api);

vi.mock("../AuthContext", () => ({
  useAuth: () => ({ loginWithGoogle: authState.loginWithGoogle }),
}));

import GoogleSignIn, { _resetGisForTests } from "./GoogleSignIn";

const ENABLED = {
  google_enabled: true,
  google_client_id: "test.apps.googleusercontent.com",
};
const DISABLED = { google_enabled: false, google_client_id: null };

function fakeGis() {
  const initialize = vi.fn();
  const renderButton = vi.fn();
  const accounts = { id: { initialize, renderButton } };
  Object.defineProperty(window, "google", {
    value: { accounts },
    configurable: true,
    writable: true,
  });
  return { initialize, renderButton };
}

beforeEach(() => {
  _resetGisForTests();
  delete window.google;
  document.head.querySelectorAll('script[src*="accounts.google.com"]').forEach((node) => node.remove());
  api.getAuthProviders.mockResolvedValue(ENABLED);
  authState.loginWithGoogle.mockResolvedValue(undefined);
  api.loginWithGoogle.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
  delete window.google;
});

describe("GoogleSignIn", () => {
  it("renders nothing when the server has no Google client ID", async () => {
    api.getAuthProviders.mockResolvedValue(DISABLED);
    const { container } = render(<GoogleSignIn onDone={() => {}} />);

    await waitFor(() => expect(api.getAuthProviders).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
    // And it never reaches for Google's script: a disabled provider means no
    // third-party request at all.
    expect(
      document.head.querySelector('script[src*="accounts.google.com"]'),
    ).toBeNull();
  });

  it("renders nothing while the providers call is still in flight", () => {
    api.getAuthProviders.mockReturnValue(new Promise(() => {}));
    const { container } = render(<GoogleSignIn onDone={() => {}} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("initializes Google with the server's client ID, once", async () => {
    const { initialize, renderButton } = fakeGis();
    render(<GoogleSignIn onDone={() => {}} />);

    await waitFor(() => expect(initialize).toHaveBeenCalledTimes(1));
    expect(initialize).toHaveBeenCalledWith(
      expect.objectContaining({
        client_id: "test.apps.googleusercontent.com",
        auto_select: false,
      }),
    );
    expect(renderButton).toHaveBeenCalledTimes(1);
  });

  it("sends the credential to the backend and reports back", async () => {
    const { initialize } = fakeGis();
    const onDone = vi.fn();
    render(<GoogleSignIn onDone={onDone} />);

    await waitFor(() => expect(initialize).toHaveBeenCalled());
    const callback = initialize.mock.calls[0][0].callback;
    await callback({ credential: "google-id-token" });

    expect(authState.loginWithGoogle).toHaveBeenCalledWith("google-id-token");
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("shows why when the backend refuses the credential", async () => {
    const { initialize } = fakeGis();
    authState.loginWithGoogle.mockRejectedValue(new Error("That Google sign-in was not accepted."));
    render(<GoogleSignIn onDone={vi.fn()} />);

    await waitFor(() => expect(initialize).toHaveBeenCalled());
    await initialize.mock.calls[0][0].callback({ credential: "bad-token" });

    expect(await screen.findByRole("alert")).toHaveTextContent(/not accepted/);
  });

  it("falls back to email when Google's script cannot load", async () => {
    // No window.google and a script that errors: the component must say so
    // rather than hang on an empty slot.
    vi.spyOn(document.head, "appendChild").mockImplementation((node) => {
      Node.prototype.appendChild.call(document.head, node);
      queueMicrotask(() => node.dispatchEvent(new Event("error")));
      return node;
    });

    render(<GoogleSignIn onDone={() => {}} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(/email works fine/i);
  });

  it("stays quiet when the providers call itself fails", async () => {
    // The email form must survive a failed providers call. No button, no
    // error: from the reader's perspective Google sign-in simply isn't there.
    api.getAuthProviders.mockRejectedValue(new Error("offline"));
    const { container } = render(<GoogleSignIn onDone={() => {}} />);

    await waitFor(() => expect(api.getAuthProviders).toHaveBeenCalled());
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
