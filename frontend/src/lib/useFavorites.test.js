import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";

const listFavorites = vi.fn();
const saveFavorite = vi.fn();
const removeFavorite = vi.fn();

vi.mock("../api", () => ({
  listFavorites: (...args) => listFavorites(...args),
  saveFavorite: (...args) => saveFavorite(...args),
  removeFavorite: (...args) => removeFavorite(...args),
}));

const AuthContext = { Consumer: () => null };

let user = null;
let authLoading = false;
vi.mock("../AuthContext", () => ({
  useAuth: () => ({ user, loading: authLoading }),
}));

const { default: useFavorites } = await import("./useFavorites");

/**
 * Saving is optimistic, so the interesting cases are the unhappy ones: a failed
 * request has to put the place back, and signing out has to drop the list rather
 * than leave the previous reader's shortlist on screen.
 */

const savedRow = (id) => ({ id, restaurant_id: id, created_at: "2026-01-01T00:00:00" });

beforeEach(() => {
  user = null;
  authLoading = false;
  listFavorites.mockReset().mockResolvedValue([]);
  saveFavorite.mockReset().mockResolvedValue({});
  removeFavorite.mockReset().mockResolvedValue(null);
});

afterEach(() => {
  vi.restoreAllMocks();
  void AuthContext;
});

describe("useFavorites", () => {
  it("does not read anything while signed out", async () => {
    renderHook(() => useFavorites());
    await waitFor(() => expect(authLoading).toBe(false));

    expect(listFavorites).not.toHaveBeenCalled();
  });

  it("does not read anything while the session is still loading", async () => {
    authLoading = true;
    renderHook(() => useFavorites());

    expect(listFavorites).not.toHaveBeenCalled();
  });

  it("loads the shortlist once signed in", async () => {
    user = { id: 1 };
    listFavorites.mockResolvedValue([savedRow(7), savedRow(9)]);

    const { result } = renderHook(() => useFavorites());

    await waitFor(() => expect(result.current.saved.size).toBe(2));
    expect(result.current.isSaved(7)).toBe(true);
    expect(result.current.isSaved(8)).toBe(false);
    expect(result.current.count).toBe(2);
  });

  it("clears the shortlist when the reader signs out", async () => {
    user = { id: 1 };
    listFavorites.mockResolvedValue([savedRow(7)]);
    const { result, rerender } = renderHook(() => useFavorites());
    await waitFor(() => expect(result.current.count).toBe(1));

    user = null;
    rerender();

    // The next reader must not inherit the previous one's places.
    await waitFor(() => expect(result.current.count).toBe(0));
  });

  it("marks a place saved before the request resolves", async () => {
    user = { id: 1 };
    let release;
    saveFavorite.mockReturnValue(new Promise((resolve) => { release = resolve; }));

    const { result } = renderHook(() => useFavorites());
    await waitFor(() => expect(result.current.signedIn).toBe(true));

    let pending;
    act(() => { pending = result.current.toggle(7); });
    expect(result.current.isSaved(7)).toBe(true);
    expect(result.current.isPending(7)).toBe(true);

    await act(async () => { release({}); await pending; });
    expect(result.current.isPending(7)).toBe(false);
    expect(result.current.isSaved(7)).toBe(true);
  });

  it("puts the place back when saving fails", async () => {
    user = { id: 1 };
    saveFavorite.mockRejectedValue(new Error("offline"));

    const { result } = renderHook(() => useFavorites());
    await waitFor(() => expect(result.current.signedIn).toBe(true));

    let ok;
    await act(async () => { ok = await result.current.toggle(7); });

    expect(ok).toBe(false);
    expect(result.current.isSaved(7)).toBe(false);
  });

  it("puts the place back when unsaving fails", async () => {
    user = { id: 1 };
    listFavorites.mockResolvedValue([savedRow(7)]);
    removeFavorite.mockRejectedValue(new Error("offline"));

    const { result } = renderHook(() => useFavorites());
    await waitFor(() => expect(result.current.isSaved(7)).toBe(true));

    let ok;
    await act(async () => { ok = await result.current.toggle(7); });

    expect(ok).toBe(false);
    expect(result.current.isSaved(7)).toBe(true);
  });

  it("keeps the list usable when the initial read fails", async () => {
    user = { id: 1 };
    listFavorites.mockRejectedValue(new Error("offline"));

    const { result } = renderHook(() => useFavorites());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.count).toBe(0);
    expect(result.current.signedIn).toBe(true);
  });

  it("tells a rapid double tap apart, so it saves then unsaves", async () => {
    user = { id: 1 };
    const { result } = renderHook(() => useFavorites());
    await waitFor(() => expect(result.current.signedIn).toBe(true));

    let first;
    let second;
    await act(async () => {
      first = result.current.toggle(7);
      second = result.current.toggle(7);
      await Promise.all([first, second]);
    });

    // The second tap decides from the state the first one left, not from a
    // stale closure, so the two requests are a save and an unsave.
    expect(saveFavorite).toHaveBeenCalledWith(7);
    expect(removeFavorite).toHaveBeenCalledWith(7);
    expect(result.current.isSaved(7)).toBe(false);
  });
});
