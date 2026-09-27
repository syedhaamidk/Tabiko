import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import useUserLocation, { LOCATION_STATUS } from "./useUserLocation";

/**
 * The location hook decides whether cards appear at all, and the rule that
 * matters is: no cards without a granted permission, and never a prompt the
 * reader did not ask for.
 */

const RAJAJINAGAR = { latitude: 12.9915, longitude: 77.5520 };

function stubBrowser({ permission = "granted", position = RAJAJINAGAR, failWith = null } = {}) {
  const calls = { getCurrentPosition: 0, query: 0 };
  let onchange = null;

  Object.defineProperty(navigator, "geolocation", {
    configurable: true,
    value: {
      getCurrentPosition: (onSuccess, onError) => {
        calls.getCurrentPosition += 1;
        if (failWith) {
          onError(failWith);
          return;
        }
        onSuccess({ coords: { ...position, accuracy: 40 }, timestamp: Date.now() });
      },
    },
  });

  Object.defineProperty(navigator, "permissions", {
    configurable: true,
    value: {
      query: async () => {
        calls.query += 1;
        return {
          state: permission,
          set onchange(handler) {
            onchange = handler;
          },
          get onchange() {
            return onchange;
          },
        };
      },
    },
  });

  return calls;
}

beforeEach(() => {
  // Nothing is cached between tests; each one declares the browser it wants.
  Object.defineProperty(navigator, "geolocation", { configurable: true, value: undefined });
  Object.defineProperty(navigator, "permissions", { configurable: true, value: undefined });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useUserLocation", () => {
  it("does not ask for a position the reader never requested", async () => {
    const calls = stubBrowser({ permission: "prompt" });

    const { result } = renderHook(() => useUserLocation());
    await waitFor(() => expect(result.current.status).toBe(LOCATION_STATUS.prompt));

    // A permission prompt on page load is the thing this hook exists to avoid.
    expect(calls.getCurrentPosition).toBe(0);
    expect(result.current.coords).toBeNull();
  });

  it("reads the position silently when permission is already granted", async () => {
    const calls = stubBrowser({ permission: "granted" });

    const { result } = renderHook(() => useUserLocation());

    await waitFor(() => expect(result.current.coords).not.toBeNull());
    expect(calls.getCurrentPosition).toBe(1);
    expect(result.current.granted).toBe(true);
  });

  it("rounds coordinates to six decimals, about a centimetre", async () => {
    stubBrowser({ position: { latitude: 12.99151234567, longitude: 77.55200876543 } });

    const { result } = renderHook(() => useUserLocation());
    await waitFor(() => expect(result.current.coords).not.toBeNull());

    expect(result.current.coords.lat).toBe(12.991512);
    expect(result.current.coords.lon).toBe(77.552009);
  });

  it("keeps the cards visible when a granted permission has no fix", async () => {
    // Code 2 is POSITION_UNAVAILABLE, not a refusal. Permission is granted, so
    // the reader still gets the full list in A-Z order rather than a gate.
    stubBrowser({ permission: "granted", failWith: { code: 2, PERMISSION_DENIED: 1 } });

    const { result } = renderHook(() => useUserLocation());

    await waitFor(() => expect(result.current.locating).toBe(false));
    expect(result.current.granted).toBe(true);
    expect(result.current.coords).toBeNull();
    expect(result.current.error).toMatch(/could not read your position/i);
  });

  it("reports denied when the reader refuses", async () => {
    stubBrowser({
      permission: "prompt",
      failWith: { code: 1, PERMISSION_DENIED: 1 },
    });

    const { result } = renderHook(() => useUserLocation());
    // Let the mount-time permission read settle first, the way a real click
    // happens long after the page has finished loading.
    await waitFor(() => expect(result.current.status).toBe(LOCATION_STATUS.prompt));

    await act(async () => {
      await result.current.request();
    });

    expect(result.current.status).toBe(LOCATION_STATUS.denied);
    expect(result.current.granted).toBe(false);
  });

  it("treats a missing geolocation API as unavailable rather than pending", async () => {
    const { result } = renderHook(() => useUserLocation());

    await waitFor(() =>
      expect(result.current.status).toBe(LOCATION_STATUS.unavailable),
    );
    expect(result.current.granted).toBe(false);
  });

  it("treats a browser that cannot describe permissions as unprompted", async () => {
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: { getCurrentPosition: () => {} },
    });
    // Firefox and Safari can refuse to describe geolocation at all.

    const { result } = renderHook(() => useUserLocation());
    await waitFor(() => expect(result.current.status).toBe(LOCATION_STATUS.prompt));
  });

  it("only calls getCurrentPosition from request()", async () => {
    const calls = stubBrowser({ permission: "prompt" });

    const { result } = renderHook(() => useUserLocation());
    await waitFor(() => expect(result.current.status).toBe(LOCATION_STATUS.prompt));
    expect(calls.getCurrentPosition).toBe(0);

    await act(async () => {
      await result.current.request();
    });
    expect(calls.getCurrentPosition).toBe(1);
  });

  it("re-reads the position on refresh", async () => {
    const calls = stubBrowser({ permission: "granted" });

    const { result } = renderHook(() => useUserLocation());
    await waitFor(() => expect(result.current.coords).not.toBeNull());

    await act(async () => {
      await result.current.refresh();
    });
    expect(calls.getCurrentPosition).toBe(2);
  });

  it("drops the stored fix when the reader revokes permission in browser settings", async () => {
    let handler = null;
    // Mutable, because the whole point is that the state changes underneath us.
    let state = "granted";

    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: {
        getCurrentPosition: (onSuccess) =>
          onSuccess({ coords: { ...RAJAJINAGAR, accuracy: 40 }, timestamp: Date.now() }),
      },
    });
    Object.defineProperty(navigator, "permissions", {
      configurable: true,
      value: {
        query: async () => ({
          get state() {
            return state;
          },
          set onchange(fn) {
            handler = fn;
          },
          get onchange() {
            return handler;
          },
        }),
      },
    });

    const { result } = renderHook(() => useUserLocation());
    await waitFor(() => expect(result.current.coords).not.toBeNull());
    expect(handler).toBeTypeOf("function");

    // A stale position must never keep driving the distance sort.
    state = "denied";
    await act(async () => {
      handler();
    });

    expect(result.current.status).toBe(LOCATION_STATUS.denied);
    expect(result.current.coords).toBeNull();
  });
});
