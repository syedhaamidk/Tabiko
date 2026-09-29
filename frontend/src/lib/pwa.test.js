/**
 * The PWA install contract: this file IS the mobile app.
 *
 * There is no native wrapper and none is planned (store fees, two build
 * chains, and review queues, for an app whose offline story — a self-drawn
 * map with zero tile requests — already works in a browser). So installing
 * from the browser has to keep working, and every requirement in that chain
 * is asserted here against the real files rather than described in a doc:
 *
 *   - the manifest parses and names every icon the install prompt needs,
 *   - the icons are really the size they claim (parsed out of the PNG bytes,
 *     not trusted from the filename),
 *   - the document links the manifest, declares a notch-aware viewport, and
 *     carries the theme color and iOS icon,
 *   - the service worker precaches the shell and the map data, never caches
 *     the API, and falls back to the shell offline.
 *
 * If any of these regresses, mobile users do not get an error — they get a
 * website that cannot be installed, which nobody reports and everybody leaves.
 */

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";
import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const PUBLIC = resolve(HERE, "../../public");
const INDEX_HTML = resolve(HERE, "../../index.html");

const read = (name) => readFileSync(join(PUBLIC, name), "utf8");

/** Width and height straight out of a PNG's IHDR chunk. No image library. */
function pngSize(path) {
  const bytes = readFileSync(path);
  const signature = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  if (!bytes.subarray(0, 8).equals(signature)) {
    throw new Error(`${path} is not a PNG`);
  }
  return {
    width: bytes.readUInt32BE(16),
    height: bytes.readUInt32BE(20),
  };
}

describe("the manifest installs the app", () => {
  const manifest = JSON.parse(read("manifest.webmanifest"));

  it("names the app and launches it standalone", () => {
    expect(manifest.name).toBeTruthy();
    expect(manifest.short_name).toBeTruthy();
    expect(manifest.display).toBe("standalone");
    expect(manifest.start_url).toBeTruthy();
  });

  it("carries the icons an install prompt requires", () => {
    const sizes = new Set(
      (manifest.icons || []).map((icon) => icon.sizes),
    );
    // 192 for the home screen, 512 for the splash, maskable for the
    // adaptive-icon crop. Missing any one of these is a silent uninstall
    // criterion on at least one platform.
    expect(sizes.has("192x192")).toBe(true);
    expect(sizes.has("512x512")).toBe(true);
    expect(
      (manifest.icons || []).some((icon) => icon.purpose === "maskable"),
    ).toBe(true);
  });

  it("points every icon at a file that exists", () => {
    for (const icon of manifest.icons || []) {
      const file = resolve(join(PUBLIC, icon.src.replace(/^\//, "")));
      expect(existsSync(file), `${icon.src} is missing`).toBe(true);
    }
  });

  it("keeps the food-map shortcut working", () => {
    // App.jsx honours ?view=map on load because the manifest shortcut links
    // there; a shortcut to a query the app ignores is a shortcut that lies.
    const shortcut = (manifest.shortcuts || []).find((entry) =>
      entry.url.includes("view=map"),
    );
    expect(shortcut, "the map shortcut is gone").toBeTruthy();
  });
});

describe("the icons are what they claim", () => {
  const cases = [
    ["icons/icon-192.png", 192, 192],
    ["icons/icon-512.png", 512, 512],
    ["icons/icon-maskable-512.png", 512, 512],
    ["icons/apple-touch-icon.png", 180, 180],
  ];

  for (const [file, width, height] of cases) {
    it(`${file} is really ${width}x${height}`, () => {
      const actual = pngSize(join(PUBLIC, file));
      expect(actual).toEqual({ width, height });
    });
  }
});

describe("the document invites installation", () => {
  const html = readFileSync(INDEX_HTML, "utf8");

  it("links the manifest", () => {
    expect(html).toMatch(/<link[^>]+rel="manifest"[^>]*>/);
  });

  it("declares a notch-aware viewport", () => {
    // Without viewport-fit=cover the page letterboxes on notched phones and
    // the safe-area CSS has nothing to work with.
    const viewport = html.match(/<meta[^>]+name="viewport"[^>]*>/);
    expect(viewport, "no viewport meta").toBeTruthy();
    expect(viewport[0]).toContain("viewport-fit=cover");
  });

  it("carries the theme color and the iOS icon", () => {
    expect(html).toMatch(/<meta[^>]+name="theme-color"[^>]*content="#FF2E88"/);
    expect(html).toMatch(/<link[^>]+rel="apple-touch-icon"[^>]*>/);
  });
});

describe("the service worker keeps its three rules", () => {
  const worker = read("sw.js");

  it("precaches the shell and the map data", () => {
    // The basemap is the product: ~900 KB that must work offline from the
    // first completed visit.
    expect(worker).toContain("/data/citywide.json");
    expect(worker).toContain("/data/neighborhoodMap.json");
    expect(worker).toContain("/manifest.webmanifest");
  });

  it("never caches the API", () => {
    // A stale "3 spots near you" is worse than an honest error, so API
    // requests bail out of the fetch handler before any cache is opened,
    // read, or written.
    expect(worker).toMatch(/pathname\.startsWith\(["']\/api\/["']\)/);
    expect(worker).toMatch(/if \(isApiRequest\(url\)\) return;/);
  });

  it("falls back to the shell when the network fails or answers badly", () => {
    // A gateway or captive portal can answer a navigation with a real 502
    // rather than rejecting it, so non-ok responses fall back too.
    expect(worker).toMatch(/response\.ok/);
    expect(worker).toContain("SHELL_DOCUMENT");
  });
});
