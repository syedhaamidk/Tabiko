/**
 * The native wrapper is configuration, not code — so it is tested as
 * configuration: every file the app stores demand must exist, parse, and
 * agree with every other file. A missing permission, a wrong package name,
 * or a mis-sized icon fails silently until store review or a black splash
 * screen, which is exactly when it is most expensive.
 *
 * What this cannot prove is left explicit: whether the projects COMPILE
 * needs Android Studio and Xcode, which do not run here. That check happens
 * on the first real build, per DEPLOY.md.
 */

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join } from "node:path";
import { describe, expect, it } from "vitest";

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(HERE, "../..");
const ANDROID_RES = join(FRONTEND, "android", "app", "src", "main", "res");
const IOS_ASSETS = join(FRONTEND, "ios", "App", "App", "Assets.xcassets");

const APP_ID = "com.tabiko.app";

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

describe("capacitor configuration", () => {
  const config = JSON.parse(
    readFileSync(join(FRONTEND, "capacitor.config.json"), "utf8"),
  );

  it("names the permanent package once, everywhere", () => {
    // The package name is immutable after the first store publish, so it is
    // asserted in the one place it is declared rather than trusted.
    expect(config.appId).toBe(APP_ID);
    expect(config.appName).toBe("Tabiko");
  });

  it("bundles the built web app, not a remote URL", () => {
    // A server.url would make the offline map a loading spinner. The bundle
    // is the product; the API root is baked in at build time instead.
    expect(config.webDir).toBe("dist");
    expect(config.server?.url).toBeUndefined();
  });
});

describe("android project", () => {
  const manifest = readFileSync(
    join(FRONTEND, "android", "app", "src", "main", "AndroidManifest.xml"),
    "utf8",
  );

  it("declares the permissions the app actually uses, and no others", () => {
    // INTERNET for the API, location for nearby sorting and walking routes.
    // Anything else here would be asking readers for data with no feature
    // behind it.
    expect(manifest).toContain("android.permission.INTERNET");
    expect(manifest).toContain("android.permission.ACCESS_COARSE_LOCATION");
    expect(manifest).toContain("android.permission.ACCESS_FINE_LOCATION");
    expect(manifest).not.toContain("CAMERA");
    expect(manifest).not.toContain("RECORD_AUDIO");
    expect(manifest).not.toContain("READ_CONTACTS");
  });

  it("points its icons at resources that exist", () => {
    expect(manifest).toContain("@mipmap/ic_launcher");
    expect(manifest).toContain("@mipmap/ic_launcher_round");
    for (const density of ["mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"]) {
      for (const name of ["ic_launcher.png", "ic_launcher_round.png"]) {
        expect(
          existsSync(join(ANDROID_RES, `mipmap-${density}`, name)),
          `mipmap-${density}/${name} is missing`,
        ).toBe(true);
      }
    }
  });

  it("sizes every legacy launcher icon to its density", () => {
    const densities = { mdpi: 48, hdpi: 72, xhdpi: 96, xxhdpi: 144, xxxhdpi: 192 };
    for (const [density, size] of Object.entries(densities)) {
      for (const name of [
        "ic_launcher.png",
        "ic_launcher_round.png",
        "ic_launcher_foreground.png",
      ]) {
        const file = join(ANDROID_RES, `mipmap-${density}`, name);
        expect(pngSize(file)).toEqual({ width: size, height: size });
      }
    }
  });

  it("keeps the adaptive-icon drawables well-formed", () => {
    // API 26+ ignores every mipmap PNG, so a malformed vector here is a
    // crash-or-blank on every modern phone while legacy icons look fine.
    // Pink lives in the background only; the foreground is the inner mark.
    // Neither may contain Capacitor's default teal.
    const background = readFileSync(
      join(ANDROID_RES, "drawable/ic_launcher_background.xml"),
      "utf8",
    );
    const foreground = readFileSync(
      join(ANDROID_RES, "drawable-v24/ic_launcher_foreground.xml"),
      "utf8",
    );
    for (const [label, text] of [
      ["background", background],
      ["foreground", foreground],
    ]) {
      expect(text, label).toContain("<vector");
      expect(text, label).not.toContain("#26A69A");
    }
    expect(background).toContain("#FF2E88");
    expect(foreground).toContain("#FFD23F");
  });

  it("ships splash screens at every committed density", () => {
    const splashes = {
      "drawable-land-hdpi": [800, 480],
      "drawable-land-mdpi": [480, 320],
      "drawable-land-xhdpi": [1280, 720],
      "drawable-land-xxhdpi": [1600, 960],
      "drawable-land-xxxhdpi": [1920, 1280],
      "drawable-port-hdpi": [480, 800],
      "drawable-port-mdpi": [320, 480],
      "drawable-port-xhdpi": [720, 1280],
      "drawable-port-xxhdpi": [960, 1600],
      "drawable-port-xxxhdpi": [1280, 1920],
      drawable: [480, 320],
    };
    for (const [dir, [width, height]] of Object.entries(splashes)) {
      const file = join(ANDROID_RES, dir, "splash.png");
      expect(existsSync(file), `${dir}/splash.png is missing`).toBe(true);
      expect(pngSize(file)).toEqual({ width, height });
    }
  });
});

describe("ios project", () => {
  it("names the app and justifies its location request", () => {
    const plist = readFileSync(
      join(FRONTEND, "ios", "App", "App", "Info.plist"),
      "utf8",
    );
    expect(plist).toContain("Tabiko");
    // iOS refuses location without this string and shows its own dialog
    // text, not an error — so a missing key reads as a broken feature.
    expect(plist).toContain("NSLocationWhenInUseUsageDescription");
  });

  it("carries a 1024 store icon", () => {
    const file = join(
      IOS_ASSETS,
      "AppIcon.appiconset",
      "AppIcon-512@2x.png",
    );
    expect(existsSync(file)).toBe(true);
    expect(pngSize(file)).toEqual({ width: 1024, height: 1024 });
  });
});

describe("the wrapper tracks the web app", () => {
  it("declares the capacitor packages it scaffolds with", () => {
    // A fresh clone runs npm install then cap sync; a missing platform
    // package turns that into "Could not find the android platform".
    const pkg = JSON.parse(
      readFileSync(join(FRONTEND, "package.json"), "utf8"),
    );
    for (const name of [
      "@capacitor/core",
      "@capacitor/cli",
      "@capacitor/android",
      "@capacitor/ios",
    ]) {
      expect(
        pkg.dependencies?.[name] ?? pkg.devDependencies?.[name],
        `${name} is not installed`,
      ).toBeTruthy();
    }
  });

  it("syncs the bundle in the documented order", () => {
    // mobile:sync builds BEFORE copying, because cap sync alone ships
    // yesterday's bundle inside today's native shell.
    const pkg = JSON.parse(
      readFileSync(join(FRONTEND, "package.json"), "utf8"),
    );
    const sync = pkg.scripts?.["mobile:sync"] ?? "";
    expect(sync.indexOf("npm run build") < sync.indexOf("cap sync")).toBe(true);
  });
});
