const ICON_PATHS = {
  south_indian: `
    <path d="M13 42c0-15 10-27 23-27 9 0 16 6 16 15 0 11-10 20-23 20-9 0-16-3-16-8Z" fill="#fff"/>
    <path d="M18 42c9 4 22 1 29-8" fill="none" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
    <circle cx="47" cy="44" r="4" fill="#C6F135" stroke="#2A0E1E" stroke-width="2"/>
    <circle cx="37" cy="49" r="3" fill="#FF6B35" stroke="#2A0E1E" stroke-width="2"/>
  `,
  north_indian: `
    <path d="M12 34h40c0 12-8 20-20 20S12 46 12 34Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <path d="M9 33h46" stroke="#2A0E1E" stroke-width="4" stroke-linecap="round"/>
    <path d="M23 26c-4-5 4-7 0-13M33 26c-4-5 4-8 0-14M43 26c-4-5 4-7 0-13" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
  `,
  chinese: `
    <path d="M11 40c2-16 11-25 21-25s19 9 21 25c-12 6-30 6-42 0Z" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M17 34l7 5M25 28l6 6M34 27l3 7M43 30l-1 7" stroke="#2A0E1E" stroke-width="2.5" stroke-linecap="round"/>
    <path d="M14 42c11 5 25 5 36 0" fill="none" stroke="#C6F135" stroke-width="3" stroke-linecap="round"/>
  `,
  italian: `
    <path d="M13 50L28 14c11 4 20 12 24 24L13 50Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <path d="M14 49c11-8 22-11 37-12" fill="none" stroke="#FF6B35" stroke-width="5" stroke-linecap="round"/>
    <circle cx="30" cy="32" r="3.5" fill="#E63946"/>
    <circle cx="38" cy="42" r="3" fill="#2D5BFF"/>
  `,
  continental: `
    <path d="M11 42h42c0 7-8 12-21 12s-21-5-21-12Z" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M14 41c3-15 10-23 18-23s15 8 18 23" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round"/>
    <circle cx="32" cy="17" r="3" fill="#C6F135" stroke="#2A0E1E" stroke-width="2"/>
    <path d="M23 51h18" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
  `,
  cafe: `
    <path d="M15 24h29v17c0 8-6 13-14 13h-1c-8 0-14-5-14-13V24Z" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M44 29h4c7 0 7 12 0 12h-4" fill="none" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M22 17c-4-5 4-7 0-12M32 17c-4-5 4-7 0-12" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
    <path d="M20 47h20" stroke="#2A0E1E" stroke-width="3" stroke-linecap="round"/>
  `,
  street: `
    <path d="M10 40c4-17 13-25 22-25s18 8 22 25H10Z" fill="#fff" stroke="#2A0E1E" stroke-width="3" stroke-linejoin="round"/>
    <path d="M12 39h40" stroke="#2A0E1E" stroke-width="4" stroke-linecap="round"/>
    <path d="M19 33l7 5M28 30l6 6M38 31l4 6" stroke="#FF2E88" stroke-width="3" stroke-linecap="round"/>
    <circle cx="18" cy="45" r="3" fill="#C6F135"/><circle cx="30" cy="45" r="3" fill="#2D5BFF"/><circle cx="42" cy="45" r="3" fill="#E63946"/>
  `,
  multi: `
    <circle cx="32" cy="34" r="20" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <circle cx="32" cy="34" r="11" fill="none" stroke="#2A0E1E" stroke-width="2" stroke-dasharray="3 4"/>
    <path d="M47 15v20M43 15v11M51 15v11" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
    <path d="M17 20l-6 14 6 4 6-4-6-14Z" fill="#C6F135" stroke="#2A0E1E" stroke-width="2"/>
  `,
  default: `
    <path d="M32 9c7 9 15 15 15 25 0 10-7 18-15 18s-15-8-15-18c0-10 8-16 15-25Z" fill="#fff" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M32 24c4 6 7 9 7 15 0 5-3 8-7 8s-7-3-7-8c0-6 3-9 7-15Z" fill="#FF6B35"/>
  `,
};

const PATTERNS = {
  dots: `<circle cx="6" cy="6" r="2" fill="#fff" opacity=".22"/><circle cx="20" cy="20" r="2" fill="#fff" opacity=".22"/>`,
  stripes: `<path d="M-4 12L12-4M4 24L24 4M16 28L28 16" stroke="#fff" stroke-width="4" opacity=".14"/>`,
  waves: `<path d="M-4 16c8-10 16 10 24 0s16 10 24 0" fill="none" stroke="#fff" stroke-width="3" opacity=".18"/>`,
  sparks: `<path d="M10 4l2 6 6 2-6 2-2 6-2-6-6-2 6-2 2-6ZM46 32l2 5 5 2-5 2-2 5-2-5-5-2 5-2 2-5Z" fill="#fff" opacity=".2"/>`,
};

function patternMarkup(pattern, patternId) {
  return `<pattern id="${patternId}" width="28" height="28" patternUnits="userSpaceOnUse">${PATTERNS[pattern] || PATTERNS.dots}</pattern>`;
}

function safeId(value) {
  return String(value || "tabiko").replace(/[^a-zA-Z0-9_-]/g, "");
}

export function foodIconSvgMarkup(visual, size = 46, instanceId = "tabiko") {
  const id = safeId(instanceId);
  const patternId = `${id}-pattern`;
  const shape = ICON_PATHS[visual.iconKey] || ICON_PATHS.default;
  return `<svg viewBox="0 0 64 64" width="${size}" height="${size}" aria-hidden="true" focusable="false" style="display:block">
    <defs>${patternMarkup(visual.pattern, patternId)}</defs>
    <path d="M12 3h40c6 0 9 4 9 10v38c0 6-4 10-10 10H13c-6 0-10-4-10-10V13C3 7 6 3 12 3Z" fill="${visual.color}" stroke="#2A0E1E" stroke-width="3"/>
    <path d="M12 3h40c6 0 9 4 9 10v38c0 6-4 10-10 10H13c-6 0-10-4-10-10V13C3 7 6 3 12 3Z" fill="url(#${patternId})"/>
    <g>${shape}</g>
  </svg>`;
}

export default function FoodGlyph({ visual, size = 48, instanceId = "tabiko" }) {
  const id = safeId(instanceId);
  const patternId = `${id}-pattern`;
  const shape = ICON_PATHS[visual.iconKey] || ICON_PATHS.default;
  return (
    <svg
      viewBox="0 0 64 64"
      width={size}
      height={size}
      aria-hidden="true"
      focusable="false"
      style={{ display: "block", overflow: "visible" }}
    >
      <defs dangerouslySetInnerHTML={{ __html: patternMarkup(visual.pattern, patternId) }} />
      <path
        d="M12 3h40c6 0 9 4 9 10v38c0 6-4 10-10 10H13c-6 0-10-4-10-10V13C3 7 6 3 12 3Z"
        fill={visual.color}
        stroke="#2A0E1E"
        strokeWidth="3"
      />
      <path
        d="M12 3h40c6 0 9 4 9 10v38c0 6-4 10-10 10H13c-6 0-10-4-10-10V13C3 7 6 3 12 3Z"
        fill={`url(#${patternId})`}
      />
      <g dangerouslySetInnerHTML={{ __html: shape }} />
    </svg>
  );
}
