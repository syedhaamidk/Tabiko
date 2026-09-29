import { useState } from "react";
import useInstallPrompt from "../lib/useInstallPrompt";
import InterfaceIcon from "./InterfaceIcon";

/**
 * Take Tabiko to go: the install button, in the app's own voice.
 *
 * The pixels that matter here belong to the topbar, not to this component:
 * the button reuses .app-button--primary, so it reads as one of the header's
 * actions rather than a third-party badge. What this component owns is when
 * anything renders at all — installed, snoozed, or incapable all render
 * nothing — plus the iOS manual path, where Apple fires no event and the
 * Share sheet steps have to be spelled out.
 */
export default function InstallButton() {
  const { canInstall, showIOSHint, dismiss, promptInstall } = useInstallPrompt();
  const [busy, setBusy] = useState(false);
  const [showSteps, setShowSteps] = useState(false);

  if (!canInstall && !showIOSHint) return null;

  async function handleInstall() {
    if (busy) return;
    setBusy(true);
    try {
      await promptInstall();
    } finally {
      setBusy(false);
    }
  }

  // Apple fires no install event, so there is nothing to hold back and
  // nothing to prompt: the button toggles the two manual steps instead.
  if (showIOSHint) {
    return (
      <span className="install install--ios">
        <button
          type="button"
          className="app-button app-button--primary install__button"
          onClick={() => setShowSteps((value) => !value)}
          aria-expanded={showSteps}
        >
          <InterfaceIcon name="scooter" size={16} /> Take Tabiko to go
        </button>
        <button
          type="button"
          className="install__dismiss"
          onClick={dismiss}
          aria-label="Not now"
        >
          <InterfaceIcon name="close" size={12} />
        </button>
        {showSteps ? (
          <p className="install__steps">
            Tap <strong>Share</strong>, then <strong>Add to Home Screen</strong>.
            Works offline, lives on your home screen.
          </p>
        ) : null}
      </span>
    );
  }

  return (
    <span className="install">
      <button
        type="button"
        className="app-button app-button--primary install__button"
        onClick={handleInstall}
        disabled={busy}
      >
        <InterfaceIcon name="scooter" size={16} /> Take Tabiko to go
      </button>
      <button
        type="button"
        className="install__dismiss"
        onClick={dismiss}
        aria-label="Not now"
      >
        <InterfaceIcon name="close" size={12} />
      </button>
    </span>
  );
}
