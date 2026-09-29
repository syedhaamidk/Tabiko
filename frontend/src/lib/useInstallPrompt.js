import { useCallback, useEffect, useState } from "react";

/**
 * The browser's install affordance, held back so the app's own button fires it.
 *
 * `beforeinstallprompt` is a one-shot per page load: whoever calls
 * preventDefault() owns the install flow, and the stashed event's prompt()
 * can only be spent once. This hook owns all of that, so components only
 * decide where the button lives and what it says.
 *
 * Three states, and only one of them shows anything:
 *   - installed (standalone display mode, or iOS standalone): never show.
 *     Offering installation to an installed app is the most embarrassing
 *     button there is.
 *   - snoozed (dismissed within the last 30 days): never show. A dismissed
 *     prompt that returns tomorrow teaches readers that dismissing does
 *     nothing.
 *   - otherwise, with a stashed event: show the button (Chromium).
 *   - otherwise, on iOS without an event: show the manual steps, because
 *     Apple fires no event at all and the Share sheet is the only path.
 */

const DISMISS_KEY = "tabiko-install-dismissed";
const SNOOZE_MS = 30 * 86400000;

function loadDismissedAt() {
  try {
    const raw = window.localStorage.getItem(DISMISS_KEY);
    return raw ? Number(raw) : 0;
  } catch {
    // Private mode without storage: behave as never dismissed rather than
    // crash the header.
    return 0;
  }
}

export function isIOSDevice() {
  const ua = window.navigator.userAgent || "";
  const ios = /iphone|ipad|ipod/i.test(ua);
  // iPads report as Macs now; touch points give them away.
  const iPadOS =
    window.navigator.platform === "MacIntel" && window.navigator.maxTouchPoints > 1;
  return (ios || iPadOS) && !window.MSStream;
}

export function isInstalled() {
  if (window.matchMedia?.("(display-mode: standalone)").matches) return true;
  // iOS standalone pages set this; everywhere else it is undefined.
  return window.navigator.standalone === true;
}

export default function useInstallPrompt() {
  const [deferred, setDeferred] = useState(null);
  const [dismissedAt, setDismissedAt] = useState(loadDismissedAt);
  const [installed, setInstalled] = useState(() => isInstalled());

  useEffect(() => {
    const onPrompt = (event) => {
      event.preventDefault();
      setDeferred(event);
    };
    const onInstalled = () => setInstalled(true);
    window.addEventListener("beforeinstallprompt", onPrompt);
    window.addEventListener("appinstalled", onInstalled);
    // Display mode can change while away (installed from the browser menu).
    setInstalled(isInstalled());
    return () => {
      window.removeEventListener("beforeinstallprompt", onPrompt);
      window.removeEventListener("appinstalled", onInstalled);
    };
  }, []);

  const snoozed =
    dismissedAt > 0 && Date.now() - dismissedAt < SNOOZE_MS;

  const dismiss = useCallback(() => {
    const now = Date.now();
    try {
      window.localStorage.setItem(DISMISS_KEY, String(now));
    } catch {
      // Storage failing must not break the header either.
    }
    setDismissedAt(now);
  }, []);

  const promptInstall = useCallback(async () => {
    if (!deferred) return "unavailable";
    // Spent exactly once: a second prompt() call throws, and the event is
    // invalid after the first use anyway.
    setDeferred(null);
    deferred.prompt();
    const { outcome } = await deferred.userChoice;
    if (outcome === "accepted") return "accepted";
    // Declining the native prompt is a dismissal with extra steps.
    dismiss();
    return "dismissed";
  }, [deferred, dismiss]);

  return {
    canInstall: Boolean(deferred) && !installed && !snoozed,
    showIOSHint: !deferred && !installed && !snoozed && isIOSDevice(),
    installed,
    dismiss,
    promptInstall,
  };
}
