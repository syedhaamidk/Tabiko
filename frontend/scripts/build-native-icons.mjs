/**
 * Rasterise the Tabiko native icons: Android launchers + splash screens and
 * the iOS app icon.
 *
 * Same geometry as everything else — paintIcon() from build-pwa-icons.mjs,
 * which shares the 64-unit design space with BrandMark.jsx — so the store
 * listing, the splash, and the in-app mark cannot drift apart. Run it after
 * any change to the mark:
 *
 *   node scripts/build-native-icons.mjs
 *
 * Splash screens are the pink canvas with the mark composited at half the
 * short edge: big enough to read on a billboard phone, small enough that the
 * rounded square never touches a screen edge on a narrow one.
 */

import { writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { encodePng, paintIcon } from "./build-pwa-icons.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ANDROID_RES = join(HERE, "..", "android", "app", "src", "main", "res");
const IOS_ICON = join(
  HERE,
  "..",
  "ios",
  "App",
  "App",
  "Assets.xcassets",
  "AppIcon.appiconset",
  "AppIcon-512@2x.png",
);

const PINK = [0xff, 0x2e, 0x88];

function emit(path, png) {
  writeFileSync(path, png);
  console.log(`${path.split("frontend")[1]}  ${png.length} bytes`);
}

/** The square mark, exactly as the PWA icons carry it. */
function mark(size) {
  return encodePng(paintIcon(size, { scale: 1 }), size);
}

/** Pink canvas with the mark composited at half the short edge. */
function splash(width, height) {
  const canvas = Buffer.alloc(width * height * 4);
  for (let i = 0; i < width * height; i += 1) {
    canvas[i * 4] = PINK[0];
    canvas[i * 4 + 1] = PINK[1];
    canvas[i * 4 + 2] = PINK[2];
    canvas[i * 4 + 3] = 255;
  }
  const edge = Math.floor(Math.min(width, height) * 0.5);
  const art = paintIcon(edge, { scale: 1 });
  const left = Math.floor((width - edge) / 2);
  const top = Math.floor((height - edge) / 2);
  for (let y = 0; y < edge; y += 1) {
    for (let x = 0; x < edge; x += 1) {
      const s = (y * edge + x) * 4;
      const alpha = art[s + 3] / 255;
      if (alpha === 0) continue;
      const d = ((top + y) * width + (left + x)) * 4;
      for (let c = 0; c < 3; c += 1) {
        canvas[d + c] = Math.round(art[s + c] * alpha + canvas[d + c] * (1 - alpha));
      }
    }
  }
  return encodePng(canvas, width, height);
}

function main() {
  // iOS wants exactly one 1024px icon; the asset catalog already names it.
  emit(IOS_ICON, mark(1024));

  // Legacy launchers, one per density. The adaptive foreground vector (not a
  // PNG) covers API 26+; these cover everything older.
  const densities = { mdpi: 48, hdpi: 72, xhdpi: 96, xxhdpi: 144, xxxhdpi: 192 };
  for (const [density, size] of Object.entries(densities)) {
    const png = mark(size);
    for (const name of ["ic_launcher.png", "ic_launcher_round.png", "ic_launcher_foreground.png"]) {
      emit(join(ANDROID_RES, `mipmap-${density}`, name), png);
    }
  }

  // Splash screens keep the repo's committed dimensions; only the pixels change.
  const splashes = [
    ["drawable-land-hdpi", 800, 480],
    ["drawable-land-mdpi", 480, 320],
    ["drawable-land-xhdpi", 1280, 720],
    ["drawable-land-xxhdpi", 1600, 960],
    ["drawable-land-xxxhdpi", 1920, 1280],
    ["drawable-port-hdpi", 480, 800],
    ["drawable-port-mdpi", 320, 480],
    ["drawable-port-xhdpi", 720, 1280],
    ["drawable-port-xxhdpi", 960, 1600],
    ["drawable-port-xxxhdpi", 1280, 1920],
    ["drawable", 480, 320],
  ];
  for (const [dir, width, height] of splashes) {
    emit(join(ANDROID_RES, dir, "splash.png"), splash(width, height));
  }
}

main();
