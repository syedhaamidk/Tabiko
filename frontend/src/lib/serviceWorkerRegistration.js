/**
 * Registers the offline shell.
 *
 * Development is excluded on purpose: a cached shell would serve yesterday's
 * bundle over today's source, which is a genuinely baffling thing to debug. The
 * registration also never blocks rendering, because a failed install must not
 * take the app down with it.
 */
export function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return;
  if (import.meta.env.DEV) return;

  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // No offline support is a downgrade, not a failure. The app is fully usable
      // online, so this is deliberately silent.
    });
  });
}
