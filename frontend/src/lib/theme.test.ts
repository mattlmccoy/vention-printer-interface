import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const themePath = join(here, "..", "theme.css");
const stylesPath = join(here, "..", "styles.css");
const indexHtmlPath = join(here, "..", "..", "index.html");
const fontsDir = join(here, "..", "..", "public", "fonts");

const css = readFileSync(themePath, "utf8");

function extractRootBlock(source: string): string {
  const match = source.match(/:root\s*{([^}]*)}/s);
  assert.ok(match, ":root block not found in theme.css");
  return match![1];
}

function declaredTokens(block: string): string[] {
  return [...block.matchAll(/(--[a-z0-9-]+)\s*:/gi)].map((m) => m[1]);
}

const rootBlock = extractRootBlock(css);

// The FLIR token set, plus --err-btn (T&C), the four axis trace tokens that replace FLIR's
// --trace-3..6, and the redesign/ux-visual re-skin additions (--label, --faint, --violet).
// theme.css is the single token source; styles.css never hardcodes a color literal.
const REQUIRED_TOKENS = [
  "--bg", "--bg-deep", "--panel", "--line", "--line-strong", "--line-control",
  "--fg", "--fg-strong", "--muted", "--label", "--faint",
  "--accent", "--accent-ink", "--focus",
  "--live", "--live-glow", "--live-glow-dim", "--live-bg",
  "--warn", "--warn-bg",
  "--err", "--err-bg",
  "--err-btn", "--rec",
  "--trace-part", "--trace-feed", "--trace-ph", "--trace-rc", "--violet",
  "--plot-1", "--plot-2", "--plot-3", "--plot-4", "--plot-warn", "--plot-band",
  "--image-bg", "--slice-bg", "--scrim", "--shadow", "--danger-ink",
  "--font-ui", "--font-mono", "--font-read",
  "--fs", "--space", "--radius",
  "--strip-w", "--rail-w", "--dock-h", "--topbar-h", "--statusbar-h",
];

test("theme.css :root defines exactly the spec's token set — nothing missing, nothing untracked", () => {
  const declared = declaredTokens(rootBlock);
  assert.deepEqual(
    [...declared].sort(),
    [...REQUIRED_TOKENS].sort(),
    "declared :root tokens must match REQUIRED_TOKENS exactly — update REQUIRED_TOKENS if theme.css intentionally changed",
  );
});

test("theme.css self-hosts IBM Plex via @font-face (no Google Fonts URLs)", () => {
  assert.match(css, /@font-face[^}]*IBM Plex Sans/);
  assert.match(css, /@font-face[^}]*IBM Plex Mono/);
  assert.doesNotMatch(css, /fonts\.googleapis\.com|fonts\.gstatic\.com/);
});

test("live green and accent amber are the spec values", () => {
  assert.match(rootBlock, /--live:\s*#5cff8a/i);
  assert.match(rootBlock, /--accent:\s*#ffb454/i);
});

test("every font url() referenced in theme.css exists under public/fonts as a real woff2 file", () => {
  const urls = [...css.matchAll(/url\("\/fonts\/([^"]+)"\)/g)].map((m) => m[1]);
  assert.ok(urls.length >= 6, "expected at least 6 self-hosted font file references in theme.css");
  for (const filename of urls) {
    const filePath = join(fontsDir, filename);
    assert.ok(existsSync(filePath), `${filename} is referenced in theme.css but missing from frontend/public/fonts`);
    const magic = readFileSync(filePath).subarray(0, 4).toString("ascii");
    assert.equal(magic, "wOF2", `${filename} does not start with the wOF2 magic bytes (got ${JSON.stringify(magic)})`);
  }
});

test("index.html sets the app title and links no external Google Fonts", () => {
  const html = readFileSync(indexHtmlPath, "utf8");
  assert.match(html, /<title>Vention Printer Interface<\/title>/);
  assert.doesNotMatch(html, /fonts\.googleapis\.com|fonts\.gstatic\.com/);
});

test("styles.css defines no :root block (theme.css is the only source of tokens)", () => {
  const styles = readFileSync(stylesPath, "utf8");
  assert.doesNotMatch(styles, /:root\s*{/, "styles.css must not re-declare :root — it would shadow theme.css's tokens");
});

test("styles.css carries no color literals — every color goes through a theme.css token", () => {
  const styles = readFileSync(stylesPath, "utf8");
  assert.doesNotMatch(styles, /#[0-9a-fA-F]{3,8}\b/, "found a hex color literal in styles.css — use a var(--token) instead");
  assert.doesNotMatch(styles, /\b(rgba?|hsla?)\(/i, "found an rgb()/rgba()/hsl()/hsla() literal in styles.css — use a var(--token) instead");
});
