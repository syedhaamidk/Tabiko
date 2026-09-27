/**
 * The two paths that break silently.
 *
 * Both are invisible in a screenshot. The token refresh only runs when a
 * short-lived access token has already expired, which is minutes after the last
 * thing anyone looked. The photo upload only fails on a real photograph from a
 * real device, which no test in the repository was doing until now.
 *
 * The two are in one file because they interact, and the interaction is the
 * interesting part: an upload that hits an expired token is sent twice, and the
 * second attempt has to carry the body and its headers correctly. That is where
 * a hand-set `Content-Type` would break a retry that works fine the first time.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const TOKEN_KEY = "tabiko_token";
const REFRESH_KEY = "tabiko_refresh";
const UPLOAD_URL = "/api/uploads";

const jsonResponse = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

/** A real Blob, not a stand-in, so the body is something `fetch` would accept. */
function aPhoto(name = "dosa.jpg", type = "image/jpeg") {
  // The leading bytes are the JPEG signature, which is what the server sniffs.
  return new File([new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46])], name, {
    type,
  });
}

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

const fetchMock = () => globalThis.fetch;

/** The calls made to the refresh endpoint, in order. */
const refreshCalls = () =>
  fetchMock().mock.calls.filter(([url]) => String(url).includes("/auth/refresh"));

/** The calls made to the upload endpoint, in order. */
const uploadCalls = () =>
  fetchMock().mock.calls.filter(([url]) => String(url) === UPLOAD_URL);

/**
 * Serve a fixed script of responses, one per call, in order.
 *
 * A `Response` body can only be read once, so handing the same object to every
 * call makes the second read empty -- which fails in a way that looks like a bug
 * in the code under test. Passing a function per slot avoids that entirely, and
 * `["reject", error]` covers the network-failure case.
 */
function script(responses) {
  let index = 0;
  fetchMock().mockImplementation(() => {
    const next = responses[index++];
    if (next === undefined) {
      throw new Error(
        `fetch was called ${index} times but the script only had ${responses.length} responses`,
      );
    }
    if (next[0] === "reject") return Promise.reject(next[1]);
    return Promise.resolve(next[0]);
  });
  return () => index;
}

// ---------- the token-refresh flow ----------

describe("token refresh on an authenticated request", () => {
  beforeEach(() => {
    api.setTokens({ access_token: "access-1", refresh_token: "refresh-1" });
  });

  it("sends the current access token", async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ ok: true }));

    await api.listFavorites();

    const [url, options] = fetchMock().mock.calls[0];
    expect(url).toBe("/api/favorites");
    expect(options.headers.Authorization).toBe("Bearer access-1");
  });

  it("refreshes once and retries with the new token after a 401", async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401))
      .mockResolvedValueOnce(
        jsonResponse({ access_token: "access-2", refresh_token: "refresh-2" }),
      )
      .mockResolvedValueOnce(jsonResponse([{ id: 1 }]));

    const result = await api.listFavorites();

    expect(result).toEqual([{ id: 1 }]);
    // The retry, not the original request, carried the new token.
    const retry = fetchMock().mock.calls[2];
    expect(retry[1].headers.Authorization).toBe("Bearer access-2");
    expect(localStorage.getItem(TOKEN_KEY)).toBe("access-2");
    expect(localStorage.getItem(REFRESH_KEY)).toBe("refresh-2");
  });

  it("refreshes exactly once even when several requests 401 together", async () => {
    // Rotation means a refresh token can only be spent once, so a second
    // concurrent refresh would present an already-spent token and end the
    // session. Routed by URL rather than by call order, because which retry
    // lands first is not something this test should depend on.
    const refreshes = [];
    fetchMock().mockImplementation((url) => {
      const path = String(url);
      if (path.includes("/auth/refresh")) {
        refreshes.push(path);
        return Promise.resolve(
          jsonResponse({ access_token: "access-2", refresh_token: "refresh-2" }),
        );
      }
      if (path === "/api/favorites") {
        return Promise.resolve(
          localStorage.getItem(TOKEN_KEY) === "access-2"
            ? jsonResponse(["a"])
            : jsonResponse({ detail: "expired" }, 401),
        );
      }
      return Promise.resolve(
        localStorage.getItem(TOKEN_KEY) === "access-2"
          ? jsonResponse(["b"])
          : jsonResponse({ detail: "expired" }, 401),
      );
    });

    const [first, second] = await Promise.all([
      api.listFavorites(),
      api.listFavoritePlaces(),
    ]);

    expect(first).toEqual(["a"]);
    expect(second).toEqual(["b"]);
    expect(refreshes).toHaveLength(1);
    expect(localStorage.getItem(TOKEN_KEY)).toBe("access-2");
  });

  it("gives up after one retry rather than looping", async () => {
    const served = script([
      [jsonResponse({ detail: "expired" }, 401)], // the original request
      [jsonResponse({ access_token: "access-2", refresh_token: "refresh-2" })], // refresh
      [jsonResponse({ detail: "still no" }, 401)], // the one retry
    ]);

    await expect(api.listFavorites()).rejects.toThrow("still no");

    // One original, one refresh, one retry. A fourth fetch would be a loop, and
    // the script throws if the code makes one.
    expect(served()).toBe(3);
    expect(refreshCalls()).toHaveLength(1);
  });

  it("does not retry at all when the refresh is itself rejected", async () => {
    const served = script([
      [jsonResponse({ detail: "expired" }, 401)],
      [jsonResponse({ detail: "refresh is dead" }, 401)],
    ]);

    await expect(api.listFavorites()).rejects.toThrow("expired");

    // The session is over. A retry here would use a token that is known dead
    // and would just fail again.
    expect(served()).toBe(2);
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("does not refresh for a 403, which is a permission answer rather than an expiry", async () => {
    fetchMock().mockResolvedValueOnce(jsonResponse({ detail: "forbidden" }, 403));

    await expect(api.listFlaggedReviews()).rejects.toThrow("forbidden");

    expect(refreshCalls()).toHaveLength(0);
  });

  it("does not attempt a refresh when there is no refresh token", async () => {
    localStorage.removeItem(REFRESH_KEY);

    fetchMock().mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401));

    await expect(api.listFavorites()).rejects.toThrow("expired");
    expect(refreshCalls()).toHaveLength(0);
  });

  it("clears both tokens when the refresh itself is rejected", async () => {
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401))
      .mockResolvedValueOnce(jsonResponse({ detail: "gone" }, 401));

    await expect(api.listFavorites()).rejects.toThrow("expired");

    // A dead refresh token left in storage would make every later request try
    // to refresh again, forever.
    expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
    expect(localStorage.getItem(REFRESH_KEY)).toBeNull();
  });

  it("keeps the token when the refresh never reached the server", async () => {
    // Offline, DNS failure, the connection dropped mid-tab. The refresh token in
    // storage is not known to be dead and may well be valid, so it stays: a
    // train tunnel must not sign a reader out. What matters is that a later
    // request can try again, which it can because the in-flight promise is
    // cleared. Clearing the token here would have been the tempting wrong
    // answer, and this is the test that says so.
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401))
      .mockRejectedValueOnce(new TypeError("network down"));

    await expect(api.listFavorites()).rejects.toThrow("expired");

    expect(localStorage.getItem(REFRESH_KEY)).toBe("refresh-1");
    expect(localStorage.getItem(TOKEN_KEY)).toBe("access-1");
  });

  it("can still refresh after a refresh that failed to reach the server", async () => {
    // The in-flight promise must be released even on the failure path, or the
    // offline reader is permanently unable to refresh once the network returns.
    const served = script([
      [jsonResponse({ detail: "expired" }, 401)],
      ["reject", new TypeError("network down")],
      [jsonResponse({ detail: "expired" }, 401)],
      [jsonResponse({ access_token: "access-9", refresh_token: "refresh-9" })],
      [jsonResponse(["back"])],
    ]);

    await expect(api.listFavorites()).rejects.toThrow("expired");
    await expect(api.listFavorites()).resolves.toEqual(["back"]);

    expect(served()).toBe(5);
    expect(localStorage.getItem(TOKEN_KEY)).toBe("access-9");
  });

  it("can refresh again after a previous refresh has finished", async () => {
    // The in-flight promise is cleared when it settles, so a session that lives
    // through several access tokens is not left unable to refresh the second.
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(
        jsonResponse({ access_token: "access-2", refresh_token: "refresh-2" }),
      )
      .mockResolvedValueOnce(jsonResponse(["ok"]))
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(
        jsonResponse({ access_token: "access-3", refresh_token: "refresh-3" }),
      )
      .mockResolvedValueOnce(jsonResponse(["ok again"]));

    await api.listFavorites();
    await expect(api.listFavorites()).resolves.toEqual(["ok again"]);
    expect(refreshCalls()).toHaveLength(2);
    expect(localStorage.getItem(TOKEN_KEY)).toBe("access-3");
  });

  it("reports the server's own message rather than a generic failure", async () => {
    fetchMock().mockResolvedValueOnce(
      jsonResponse({ detail: [{ msg: "rating must be at least 1" }] }, 422),
    );

    await expect(api.addDish(1, "Dosa", null)).rejects.toThrow(
      "rating must be at least 1",
    );
  });
});

// ---------- the photo-upload flow ----------

describe("photo upload", () => {
  beforeEach(() => {
    api.setTokens({ access_token: "access-1", refresh_token: "refresh-1" });
  });

  it("posts the file and returns the path the server will serve it from", async () => {
    fetchMock().mockResolvedValueOnce(
      jsonResponse({ url: "/uploads/abc-123.jpg", content_type: "image/jpeg", size: 8 }, 201),
    );
    const photo = aPhoto();

    const result = await api.uploadImage(photo);

    expect(result).toEqual({
      url: "/uploads/abc-123.jpg",
      content_type: "image/jpeg",
      size: 8,
    });

    const [url, options] = fetchMock().mock.calls[0];
    expect(url).toBe(UPLOAD_URL);
    expect(options.method).toBe("POST");
    expect(options.body).toBe(photo);
    expect(options.headers.Authorization).toBe("Bearer access-1");
  });

  it("does not set Content-Type, so the browser supplies the boundary", async () => {
    // The single most common way to break an upload: setting
    // `multipart/form-data` by hand. The boundary is generated by the browser
    // and goes in that header, so setting it produces a body the server cannot
    // parse -- and the error blames the server.
    fetchMock().mockResolvedValueOnce(jsonResponse({ url: "/uploads/x.jpg" }, 201));

    await api.uploadImage(aPhoto());

    const headers = fetchMock().mock.calls[0][1].headers;
    expect(headers.Authorization).toBe("Bearer access-1");
    expect(
      Object.keys(headers).some((key) => key.toLowerCase() === "content-type"),
    ).toBe(false);
  });

  it("needs an account", async () => {
    localStorage.clear();
    fetchMock().mockResolvedValueOnce(jsonResponse({ detail: "no" }, 401));

    await expect(api.uploadImage(aPhoto())).rejects.toThrow("no");
    expect(refreshCalls()).toHaveLength(0);
  });

  it("surfaces the server's reason for refusing a file that lies about its type", async () => {
    // A text file renamed to .jpg: the browser reports `image/jpeg` because that
    // is the extension, so the client-side guard lets it through and the
    // server's magic-number check is the only thing that can catch it. This is
    // the case that matters, and the reason the guard above is a shortcut
    // rather than the check.
    const disguised = new File(["this is plain text, not a JPEG"], "notes.jpg", {
      type: "image/jpeg",
    });
    fetchMock().mockResolvedValueOnce(
      jsonResponse({ detail: "That is not a PNG, JPEG, GIF, WEBP or BMP." }, 422),
    );

    await expect(api.uploadImage(disguised)).rejects.toThrow("not a PNG");
    expect(uploadCalls()).toHaveLength(1);
  });

  it("re-sends the photo intact when the token expired mid-upload", async () => {
    // The interaction worth having a test for. An upload is the one request
    // whose body is large enough that re-sending it twice is a real cost, and
    // the one most likely to be dropped on the retry if the body is a
    // one-shot stream.
    fetchMock()
      .mockResolvedValueOnce(jsonResponse({ detail: "expired" }, 401))
      .mockResolvedValueOnce(
        jsonResponse({ access_token: "access-2", refresh_token: "refresh-2" }),
      )
      .mockResolvedValueOnce(
        jsonResponse({ url: "/uploads/late.jpg", content_type: "image/jpeg", size: 8 }, 201),
      );

    const photo = aPhoto();
    const result = await api.uploadImage(photo);

    expect(result.url).toBe("/uploads/late.jpg");
    expect(uploadCalls()).toHaveLength(2);
    // The same object went out both times, and is still readable afterwards.
    expect(uploadCalls()[0][1].body).toBe(photo);
    expect(uploadCalls()[1][1].body).toBe(photo);
    expect(photo.size).toBe(8);
    // And the retry was authenticated with the refreshed token.
    expect(uploadCalls()[1][1].headers.Authorization).toBe("Bearer access-2");
  });

  it("clears the session rather than retrying forever if the upload is still rejected", async () => {
    const served = script([
      [jsonResponse({ detail: "expired" }, 401)],
      [jsonResponse({ access_token: "access-2", refresh_token: "refresh-2" })],
      [jsonResponse({ detail: "still expired" }, 401)],
    ]);

    await expect(api.uploadImage(aPhoto())).rejects.toThrow("still expired");

    // Exactly three calls, not a loop. Uploads are capped at 30 an hour, and an
    // unbounded retry would spend the reader's whole allowance on one photo.
    expect(served()).toBe(3);
    expect(uploadCalls()).toHaveLength(2);
    expect(refreshCalls()).toHaveLength(1);
  });

  it("rejects a file that is not an image before anything else happens", async () => {
    // Guard on the client, so the reader finds out while they can still change
    // the photo rather than after the review is written.
    await expect(api.uploadImage(new File(["x"], "notes.txt", { type: "text/plain" }))).rejects.toThrow(
      /image|png|jpeg/i,
    );
    expect(fetchMock()).not.toHaveBeenCalled();
  });
});
