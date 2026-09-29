import { useEffect, useRef, useState } from "react";
import { useAuth } from "../AuthContext";
import * as api from "../api";

const GIS_SCRIPT = "https://accounts.google.com/gsi/client";

/**
 * Load Google Identity Services exactly once per page.
 *
 * Module-level, not per-component: three sign-in buttons on one page must not
 * insert three script tags and initialize three times. The promise is shared,
 * so the second caller attaches to the first caller's load.
 */
let gisPromise = null;

function loadGis() {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (!gisPromise) {
    gisPromise = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = GIS_SCRIPT;
      script.async = true;
      script.defer = true;
      script.onload = () => resolve();
      script.onerror = () =>
        reject(new Error("Google's script could not be loaded"));
      document.head.appendChild(script);
    });
  }
  return gisPromise;
}

/** Test seam: component tests must not inherit a loaded-or-failed script. */
export function _resetGisForTests() {
  gisPromise = null;
}

/**
 * A Google sign-in button beside the email form.
 *
 * Renders nothing at all when the server has no Google client ID, or when the
 * providers call or the Google script fails — the email form is the whole
 * auth surface then, and a dead button would be worse than no button. The
 * button itself is drawn by Google (their branding rules require it), so this
 * component owns the loading, the callback wiring, and the error states
 * around it, and nothing visual.
 *
 * The "or" divider lives inside, next to the slot, for one reason: it must be
 * impossible for a divider to render without a button after it. A divider
 * that outlives a failed load reads as a broken promise.
 *
 * `layout="inline"` sits the divider and the button in the row with the email
 * buttons; `layout="block"` stacks them full-width under a form. The caller
 * picks, and the component guarantees both stay consistent.
 *
 * The credential Google hands back is an ID token, not a session: it goes to
 * POST /auth/google, which verifies the signature and returns normal Tabiko
 * tokens. It is never stored, never logged, and never sent anywhere else.
 */
export default function GoogleSignIn({ onDone, layout = "inline" }) {
  const { loginWithGoogle } = useAuth();
  const [clientId, setClientId] = useState(null);
  const [error, setError] = useState(null);
  const buttonRef = useRef(null);
  const mounted = useRef(true);
  // The callback outlives renders, so it reads these rather than closing over
  // a stale onDone from the render that initialized the button.
  const callbackRefs = useRef({ loginWithGoogle, onDone });
  callbackRefs.current = { loginWithGoogle, onDone };

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    api
      .getAuthProviders()
      .then((providers) => {
        if (!cancelled && providers.google_enabled && providers.google_client_id) {
          setClientId(providers.google_client_id);
        }
      })
      .catch(() => {
        // Providers failing must not break the email form. No button, no error:
        // from the reader's perspective Google sign-in simply isn't there.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!clientId) return undefined;
    let cancelled = false;

    async function setup() {
      try {
        await loadGis();
      } catch {
        if (!cancelled && mounted.current) {
          setError("Google sign-in could not load. Email works fine instead.");
        }
        return;
      }
      if (cancelled || !mounted.current || !buttonRef.current) return;
      try {
        window.google.accounts.id.initialize({
          client_id: clientId,
          // One-shot per sign-in: Google forbids automatic sign-in here
          // (no auto_select), so every session starts with a deliberate tap.
          auto_select: false,
          callback: async (response) => {
            const { loginWithGoogle: login, onDone: done } = callbackRefs.current;
            setError(null);
            try {
              await login(response.credential);
              done?.();
            } catch (caught) {
              if (mounted.current) {
                setError(
                  caught.message || "Google sign-in did not work. Try email instead.",
                );
              }
            }
          },
        });
        window.google.accounts.id.renderButton(buttonRef.current, {
          theme: "outline",
          size: "large",
          shape: "pill",
          text: "continue_with",
          width: 280,
        });
      } catch {
        if (!cancelled && mounted.current) {
          setError("Google sign-in could not start. Email works fine instead.");
        }
      }
    }

    setup();
    return () => {
      cancelled = true;
    };
  }, [clientId]);

  if (!clientId) return null;

  return (
    <span className={`google-signin google-signin--${layout}`}>
      <span className="auth-divider" aria-hidden="true">
        or
      </span>
      <span ref={buttonRef} data-testid="google-button-slot" />
      {error ? (
        <span className="auth-error" role="alert">
          {error}
        </span>
      ) : null}
    </span>
  );
}
