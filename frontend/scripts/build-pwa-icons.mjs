/**
 * Rasterise the Tabiko app icons.
 *
 * There is no image toolchain in this project and adding one just to emit four
 * squares would be heavier than the icons themselves, so this paints them
 * directly. Shapes are signed distance fields in the same 64-unit design space
 * as BrandMark.jsx, so the icon and the in-app mark share one geometry rather
 * than two drawings that can drift.
 *
 * Output is a real 8-bit RGBA PNG, assembled by hand: signature, IHDR, one IDAT
 * of deflated scanlines, IEND. Node's zlib does the compression.
 *
 *   node scripts/build-pwa-icons.mjs
 */

import { deflateSync } from "node:zlib";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT_DIR = join(HERE, "..", "public", "icons");

// Brand palette, matching global.css.
const PINK = [0xff, 0x2e, 0x88];
const YELLOW = [0xff, 0xd2, 0x3f];
const BLUE = [0x2d, 0x5b, 0xff];
const ORANGE = [0xff, 0x6b, 0x35];
const INK = [0x2a, 0x0e, 0x1e];
const WHITE = [0xff, 0xff, 0xff];

// ---------- signed distance fields ----------

const circle = (px, py, cx, cy, r) => Math.hypot(px - cx, py - cy) - r;

const ring = (px, py, cx, cy, r, width) =>
  Math.abs(circle(px, py, cx, cy, r)) - width / 2;

function roundedBox(px, py, minX, minY, maxX, maxY, radius) {
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;
  const hx = (maxX - minX) / 2 - radius;
  const hy = (maxY - minY) / 2 - radius;
  const dx = Math.max(Math.abs(px - cx) - hx, 0);
  const dy = Math.max(Math.abs(py - cy) - hy, 0);
  return Math.min(Math.max(Math.abs(px - cx) - hx, Math.abs(py - cy) - hy), 0) +
    Math.hypot(dx, dy) - radius;
}

/**
 * Smooth union. A plain min() of the flame's circles would leave visible seams
 * where they meet; blending the fields keeps the silhouette continuous.
 */
function smoothUnion(a, b, k) {
  const h = Math.max(k - Math.abs(a - b), 0) / k;
  return Math.min(a, b) - h * h * k * 0.25;
}

// The flame: one broad base circle tapering to a tip, mirroring the teardrop in
// BrandMark.jsx. Expressed as a chain of blended circles so the raster and the
// vector describe the same shape.
function flameDistance(px, py) {
  let d = circle(px, py, 32, 39, 11);
  d = smoothUnion(d, circle(px, py, 32, 31, 8.5), 5);
  d = smoothUnion(d, circle(px, py, 32, 24, 5.5), 4);
  d = smoothUnion(d, circle(px, py, 32, 18.5, 2.6), 3);
  return d;
}

// The orange core inside the flame, a smaller copy sitting low in the bowl.
function innerFlameDistance(px, py) {
  let d = circle(px, py, 32, 40, 6);
  d = smoothUnion(d, circle(px, py, 32, 34, 4.2), 3);
  d = smoothUnion(d, circle(px, py, 32, 29.5, 2), 2);
  return d;
}

// ---------- painting ----------

/**
 * @param size    output edge in pixels
 * @param scale   mark size relative to the canvas; 1 fills it
 * @param padding keep-out for maskable icons, as a fraction of the canvas
 */
function paintIcon(size, { scale = 1, inset = 0 } = {}) {
  const pixels = Buffer.alloc(size * size * 4);
  const SS = 3; // supersamples per axis
  const unit = (size / 64) * scale;
  // Centre the mark, then shrink it for a maskable safe zone.
  const originX = size / 2 - 32 * unit;
  const originY = size / 2 - 32 * unit;
  const bleed = inset > 0;

  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      let r = 0;
      let g = 0;
      let b = 0;
      let a = 0;

      for (let sy = 0; sy < SS; sy += 1) {
        for (let sx = 0; sx < SS; sx += 1) {
          // Invert the design-unit -> pixel transform to sample the field.
          const px = (x + (sx + 0.5) / SS - originX) / unit;
          const py = (y + (sy + 0.5) / SS - originY) / unit;
          const [cr, cg, cb, ca] = sample(px, py, bleed);
          r += cr * ca;
          g += cg * ca;
          b += cb * ca;
          a += ca;
        }
      }

      const samples = SS * SS;
      const offset = (y * size + x) * 4;
      if (a > 0) {
        // Un-premultiply so partially covered edges keep their colour.
        pixels[offset] = Math.round(r / a);
        pixels[offset + 1] = Math.round(g / a);
        pixels[offset + 2] = Math.round(b / a);
      }
      pixels[offset + 3] = Math.round((a / samples) * 255);
    }
  }
  return pixels;
}

/** Painter's algorithm: background, then each layer of the mark. */
function sample(px, py, bleed) {
  // A maskable icon is cropped by the launcher, so the background runs to every
  // edge and only the mark itself is inset.
  const onBackground =
    bleed || roundedBox(px, py, 3, 4, 61, 60, 11) < 0;
  if (!onBackground) return [0, 0, 0, 0];
  if (innerFlameDistance(px, py) < 0) return [...ORANGE, 1];
  if (flameDistance(px, py) < 0) return [...WHITE, 1];
  if (circle(px, py, 32, 33, 11) < 0) return [...BLUE, 1];
  if (circle(px, py, 32, 33, 19) < 0) return [...YELLOW, 1];
  if (ring(px, py, 32, 33, 19, 3) < 0) return [...INK, 1];
  if (ring(px, py, 32, 33, 11, 2.5) < 0) return [...INK, 1];
  return [...PINK, 1];
}

// ---------- PNG encoding ----------

const CRC_TABLE = (() => {
  const table = new Int32Array(256);
  for (let n = 0; n < 256; n += 1) {
    let c = n;
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    }
    table[n] = c;
  }
  return table;
})();

function crc32(buffer) {
  let crc = -1;
  for (let i = 0; i < buffer.length; i += 1) {
    crc = CRC_TABLE[(crc ^ buffer[i]) & 0xff] ^ (crc >>> 8);
  }
  return (crc ^ -1) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body), 0);
  return Buffer.concat([length, body, crc]);
}

function encodePng(pixels, size) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(size, 0);
  ihdr.writeUInt32BE(size, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // colour type: RGBA
  ihdr[10] = 0; // deflate
  ihdr[11] = 0; // adaptive filtering
  ihdr[12] = 0; // no interlace

  // One filter byte (0 = None) per scanline.
  const stride = size * 4;
  const raw = Buffer.alloc((stride + 1) * size);
  for (let y = 0; y < size; y += 1) {
    raw[y * (stride + 1)] = 0;
    pixels.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", ihdr),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// ---------- emit ----------

mkdirSync(OUT_DIR, { recursive: true });

const TARGETS = [
  // Any-purpose icons carry the mark with its rounded-square edge.
  { name: "icon-192.png", size: 192, options: { scale: 1 } },
  { name: "icon-512.png", size: 512, options: { scale: 1 } },
  // iOS does not apply rounded masks, so it gets the same square icon.
  { name: "apple-touch-icon.png", size: 180, options: { scale: 1 } },
  // Maskable icons are cropped to a circle by some launchers, so the mark is
  // shrunk into the safe zone on a full-bleed background.
  { name: "icon-maskable-512.png", size: 512, options: { scale: 0.74, inset: 1 } },
  { name: "favicon-64.png", size: 64, options: { scale: 1 } },
];

for (const target of TARGETS) {
  const png = encodePng(paintIcon(target.size, target.options), target.size);
  writeFileSync(join(OUT_DIR, target.name), png);
  console.log(`${target.name}  ${target.size}x${target.size}  ${png.length} bytes`);
}
