import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Reads the browser's geolocation permission and, once granted, the position
 * itself.
 *
 * The permission is checked on mount but the position is never requested
 * unprompted, because getCurrentPosition fires a browser permission dialog the
 * user did not ask for. That matches the location gate: no permission, no
 * nearby cards.
 *
 * Permission and position are deliberately separate states. A granted permission
 * with a failed GPS fix still lets the reader browse the full list, because a
 * weak signal should not hide the whole city.
 */

export const LOCATION_STATUS = {
  checking: "checking",
  granted: "granted",
  prompt: "prompt",
  denied: "denied",
  unavailable: "unavailable",
};

// A cached fix under two minutes old is close enough for "how far is this
// place"; anything older is worth re-reading when the user asks to refresh.
const MAX_AGE_MS = 120_000;
const TIMEOUT_MS = 10_000;

// Six decimals is roughly 10 cm, far past anything the distances need.
function round6(value) {
  return Math.round(value * 1e6) / 1e6;
}

function readPermissionState() {
  if (typeof navigator === "undefined" || !navigator.geolocation) {
    return Promise.resolve(LOCATION_STATUS.unavailable);
  }
  if (!navigator.permissions?.query) return Promise.resolve(LOCATION_STATUS.prompt);
  return navigator.permissions
    .query({ name: "geolocation" })
    .then((status) => status.state)
    .catch(() => {
      // Firefox and Safari can refuse to describe geolocation.
      return LOCATION_STATUS.prompt;
    });
}

export default function useUserLocation() {
  const [status, setStatus] = useState(LOCATION_STATUS.checking);
  const [coords, setCoords] = useState(null);
  const [locating, setLocating] = useState(false);
  const [error, setError] = useState(null);
  const permissionRef = useRef(null);

  const locate = useCallback((permissionState) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setStatus(LOCATION_STATUS.unavailable);
      return;
    }
    setLocating(true);
    setError(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setLocating(false);
        setCoords({
          lat: round6(position.coords.latitude),
          lon: round6(position.coords.longitude),
        });
        setStatus(LOCATION_STATUS.granted);
      },
      (failure) => {
        setLocating(false);
        const denied = failure?.code === failure?.PERMISSION_DENIED;
        setError(
          denied
            ? "Location access was turned off."
            : "Could not read your position, so places are not sorted by distance.",
        );
        setStatus(
          denied ? LOCATION_STATUS.denied : permissionState ?? LOCATION_STATUS.prompt,
        );
      },
      { enableHighAccuracy: false, timeout: TIMEOUT_MS, maximumAge: MAX_AGE_MS },
    );
  }, []);

  useEffect(() => {
    let active = true;

    readPermissionState().then((initial) => {
      if (!active) return;
      setStatus(initial);
      if (navigator.permissions?.query) {
        navigator.permissions
          .query({ name: "geolocation" })
          .then((permission) => {
            if (!active) return;
            permissionRef.current = permission;
            permission.onchange = () => {
              if (!active) return;
              setStatus(permission.state);
              // Losing permission has to lose the fix with it, or a stale
              // position would keep driving the sort.
              if (permission.state !== LOCATION_STATUS.granted) {
                setCoords(null);
              }
            };
          })
          .catch(() => {});
      }
      // Already granted: reading the position cannot prompt, so do it silently.
      if (initial === LOCATION_STATUS.granted) locate(initial);
    });

    return () => {
      active = false;
      if (permissionRef.current) permissionRef.current.onchange = null;
    };
  }, [locate]);

  const request = useCallback(() => locate(permissionRef.current?.state), [locate]);
  const refresh = useCallback(() => locate(LOCATION_STATUS.granted), [locate]);

  return {
    status,
    coords,
    locating,
    error,
    granted: status === LOCATION_STATUS.granted,
    /** Ask the browser for permission. Only ever called from a real click. */
    request,
    /** Re-read the position. Only meaningful once permission is granted. */
    refresh,
  };
}
