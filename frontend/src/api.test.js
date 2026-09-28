import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Transparent session refresh.
 *
 * Access tokens are short-lived on purpose, so a session outlives several of
 * them. The reader must never notice that, and must never be signed out for
 * leaving a tab open. The cases that matter are the concurrent ones, because
 * rotation means a token can only be spent once.
 */

const TOKEN_KEY = "tabiko_token";
const REFRESH_KEY = "tabiko_refresh";

const jsonResponse = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

let api;

beforeEach(async () => {
  localStorage.clear();
  vi.resetModules();
  vi.stubGlobal("fetch", vi.fn());
  api = await import("./api");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

/** The stubbed fetch itself, so `.mockResolvedValue` and `.mock` both work. */
const fetchMock = () => globalThis.fetch;

describe("token storage", () => {
  it("keeps the access and refresh tokens apart", () => {
    api.setTokens({ access_token: "a1", refresh_token: "r1" });
    expect(localStorage.getItem(TOKEN_KEY)).toBe("a1");
    expect(localStorage.getItem(REFRESH_KEY)).toBe("r1");
    expect(api.getToken()).toBe("a1");
    expect(api.getRefreshToken()).toBe("r1");
  });

  it("clears both halves on sign out", () => {
    api.setTokens({ access_token: "a1", refresh_token: "r1" });
    api.clearToken();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("still accepts a bare access token, which the test client uses", () => {
    api.setToken("only-access");
    expect(api.getToken()).toBe("only-access");
  });
});

describe("logout", () => {
  it("revokes the session before clearing it locally", async () => {
    api.setTokens({ access_token: "a1", refresh_token: "r1" });
    fetchMock().mockResolvedValue(new Response(null, { status: 204 }));

    await api.logout();

    const [url, options] = fetchMock().mock.calls[0];
    expect(url).toContain("/auth/logout");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body).refresh_token).toBe("r1");
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("clears the session even when the server cannot be reached", async () => {
    api.setTokens({ access_token: "a1", refresh_token: "r1" });
    fetchMock().mockRejectedValue(new Error("offline"));

    await expect(api.logout()).resolves.toBeNull();
    // Signing out must work on a train with no signal.
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("does not call the server when there was no session", async () => {
    await api.logout();
    expect(fetchMock()).not.toHaveBeenCalled();
  });
});

describe("transparent refresh", () => {
  it("refreshes once and retries the original request", async () => {
    api.setTokens({ access_token: "expired", refresh_token: "r1" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ detail: "Invalid or expired token" }, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: "a2", refresh_token: "r2" }))
      .mockResolvedValueOnce(jsonResponse([{ id: 1 }]));

    const rows = await api.listFavorites();

    expect(rows).toEqual([{ id: 1 }]);
    expect(fetchMock()).toHaveBeenCalledTimes(3);
    expect(localStorage.getItem(TOKEN_KEY)).toBe("a2");
    // Rotation: the new session replaces the old one rather than adding to it.
    expect(localStorage.getItem(REFRESH_KEY)).toBe("r2");
  });

  it("sends the refreshed token on the retry", async () => {
    api.setTokens({ access_token: "expired", refresh_token: "r1" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: "a2", refresh_token: "r2" }))
      .mockResolvedValueOnce(jsonResponse([]));

    await api.listFavorites();

    const retry = fetchMock().mock.calls[2][1];
    expect(retry.headers.Authorization).toBe("Bearer a2");
  });

  it("gives up rather than looping when the new token is also refused", async () => {
    api.setTokens({ access_token: "expired", refresh_token: "r1" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: "a2", refresh_token: "r2" }))
      .mockResolvedValueOnce(jsonResponse({}, 401));

    await expect(api.listFavorites()).rejects.toMatchObject({ status: 401 });
    // One attempt only. A retry loop here would be a self-inflicted stampede.
    expect(fetchMock()).toHaveBeenCalledTimes(3);
  });

  it("clears the session when the refresh token is no longer accepted", async () => {
    api.setTokens({ access_token: "expired", refresh_token: "dead" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: "session expired" }, 401));

    await expect(api.listFavorites()).rejects.toMatchObject({ status: 401 });
    // A dead refresh token must not be retried on every subsequent request.
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
  });

  it("does not attempt a refresh when there is no session", async () => {
    fetchMock().mockResolvedValue(jsonResponse({}, 401));

    await expect(api.listFavorites()).rejects.toMatchObject({ status: 401 });
    expect(fetchMock()).toHaveBeenCalledTimes(1);
  });

  it("shares one refresh between concurrent requests", async () => {
    api.setTokens({ access_token: "expired", refresh_token: "r1" });
    let releaseRefresh;
    const refreshGate = new Promise((resolve) => {
      releaseRefresh = resolve;
    });
    fetchMock().mockImplementation((url) => {
      if (String(url).includes("/auth/refresh")) {
        return refreshGate.then(() =>
          jsonResponse({ access_token: "a2", refresh_token: "r2" }),
        );
      }
      return Promise.resolve(jsonResponse({}, 401));
    });

    const first = api.listFavorites();
    const second = api.listFavorites();
    // Both hit 401 and both reach for the refresh at the same time.
    releaseRefresh();
    await Promise.allSettled([first, second]);

    // Rotation would break the second request if it spent the same token twice.
    const refreshCalls = fetchMock().mock.calls.filter(([url]) =>
      String(url).includes("/auth/refresh"),
    );
    expect(refreshCalls).toHaveLength(1);
  });

  it("leaves a 403 alone, because refreshing cannot help", async () => {
    api.setTokens({ access_token: "good", refresh_token: "r1" });
    fetchMock().mockResolvedValue(jsonResponse({ detail: "Administrator access required" }, 403));

    await expect(api.listFavorites()).rejects.toMatchObject({ status: 403 });
    // No refresh: the token was fine, the reader simply is not allowed.
    expect(fetchMock()).toHaveBeenCalledTimes(1);
  });

  it("survives a refresh that fails at the network level", async () => {
    api.setTokens({ access_token: "expired", refresh_token: "r1" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockRejectedValueOnce(new Error("offline"));

    await expect(api.listFavorites()).rejects.toMatchObject({ status: 401 });
  });

  it("preserves the caller's method and body on the retry", async () => {
    api.setTokens({ access_token: "expired", refresh_token: "r1" });
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: "a2", refresh_token: "r2" }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await api.removeFavorite(7);

    const retry = fetchMock().mock.calls[2][1];
    expect(retry.method).toBe("DELETE");
  });
});

describe("unauthenticated calls", () => {
  it("does not attach a token it does not have", async () => {
    fetchMock().mockResolvedValue(jsonResponse({ places: 7728 }));

    await api.fetchStats();

    // fetchStats is a plain public call, so it sends no options at all.
    const [, options] = fetchMock().mock.calls[0];
    expect(options?.headers?.Authorization).toBeUndefined();
  });

  it("never retries a public endpoint", async () => {
    fetchMock().mockResolvedValue(jsonResponse([], 401));
    await expect(api.listRestaurants()).rejects.toMatchObject({ status: 401 });
    expect(fetchMock()).toHaveBeenCalledTimes(1);
  });
});

describe("google sign-in", () => {
  it("sends the ID token and returns the session untouched", async () => {
    const session = { access_token: "a1", refresh_token: "r1", expires_in: 1800 };
    fetchMock().mockResolvedValue(jsonResponse(session));

    await expect(api.loginWithGoogle("google-id-token")).resolves.toEqual(session);

    const [url, options] = fetchMock().mock.calls[0];
    expect(url).toBe("/api/auth/google");
    expect(options.method).toBe("POST");
    expect(JSON.parse(options.body)).toEqual({ id_token: "google-id-token" });
  });

  it("does not go through the refresh machinery", async () => {
    // There is no session yet, so a 401 means Google said no — not that an
    // access token expired. Retrying with a refresh would be nonsense twice
    // over: there is no refresh token, and the failure is not an expiry.
    fetchMock().mockResolvedValue(jsonResponse({ detail: "no" }, 401));

    await expect(api.loginWithGoogle("bad-token")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock()).toHaveBeenCalledTimes(1);
  });

  it("reads which front doors exist", async () => {
    fetchMock().mockResolvedValue(
      jsonResponse({ google_enabled: true, google_client_id: "test.apps.googleusercontent.com" }),
    );

    await expect(api.getAuthProviders()).resolves.toEqual({
      google_enabled: true,
      google_client_id: "test.apps.googleusercontent.com",
    });
    expect(fetchMock().mock.calls[0][0]).toBe("/api/auth/providers");
  });
});
