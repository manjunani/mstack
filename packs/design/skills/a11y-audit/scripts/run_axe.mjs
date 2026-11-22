#!/usr/bin/env node
// Scan pages with axe-core in Chromium through the project's own Playwright, and walk each page with Tab.
// Usage: node run_axe.mjs --url <address> [--url <address> ...] --out <new folder> [--width 1280] [--max-stops 200]
// Writes <out>/axe.json (format read by audit.py) and <out>/keyboard.json. Reads pages only; never clicks or types text.
// Needs, resolved from the current folder: playwright (or playwright-core) and axe-core. Missing -> exit 2 with what to get.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const urls = [];
let out = '';
let width = 1280;
let maxStops = 200;
for (let i = 0; i < args.length; i += 1) {
  if (args[i] === '--url') urls.push(args[++i]);
  else if (args[i] === '--out') out = args[++i];
  else if (args[i] === '--width') width = parseInt(args[++i], 10);
  else if (args[i] === '--max-stops') maxStops = parseInt(args[++i], 10);
  else if (args[i] === '--help' || args[i] === '-h') {
    console.log('node run_axe.mjs --url <address> [--url ...] --out <new folder> [--width 1280] [--max-stops 200]');
    process.exit(0);
  }
}
if (!urls.length || !out) {
  console.log('RESULT not verified: give at least one --url and an --out folder');
  process.exit(2);
}
if (fs.existsSync(out)) {
  console.log(`RESULT not verified: ${out} already exists; give a new folder`);
  process.exit(2);
}

const require = createRequire(path.join(process.cwd(), 'package.json'));
const load = (names) => {
  for (const name of names) {
    try { return { name, mod: require(name) }; } catch (e) { /* try the next one */ }
  }
  return null;
};
const pw = load(['playwright', 'playwright-core', '@playwright/test']);
let axePath = null;
try { axePath = require.resolve('axe-core/axe.min.js'); } catch (e) { /* missing */ }
const missing = [];
if (!pw) missing.push('playwright (npm install --save-dev playwright, then npx playwright install chromium)');
if (!axePath) missing.push('axe-core (npm install --save-dev axe-core)');
if (missing.length) {
  console.log(`missing in ${process.cwd()}: ${missing.join('; ')}`);
  console.log('blocked: the scan needs these in the project; ask the user to add them');
  process.exit(2);
}

let browser;
try {
  browser = await pw.mod.chromium.launch();
} catch (e) {
  console.log(`cannot start Chromium: ${String(e.message || e).split('\n')[0]}`);
  console.log('blocked: run npx playwright install chromium, then try again');
  process.exit(2);
}
const axeSource = fs.readFileSync(axePath, 'utf8');
const runs = [];
const passes = [];
for (const url of urls) {
  const page = await browser.newPage({ viewport: { width, height: 900 } });
  await page.goto(url, { waitUntil: 'load' });
  await page.addScriptTag({ content: axeSource });
  const results = await page.evaluate(() => window.axe.run(document, { resultTypes: ['violations', 'incomplete'] }));
  runs.push({ view: `${width}/light/default ${url}`, results });
  // Keyboard pass: press Tab, record where focus is and whether anything shows it.
  const stops = [];
  let ended = 'limit';
  let first = null;
  for (let n = 0; n < maxStops; n += 1) {
    await page.keyboard.press('Tab');
    const stop = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el || el === document.body || el === document.documentElement) return null;
      const sel = (node) => {
        const parts = [];
        for (let x = node; x && x.nodeType === 1 && parts.length < 4; x = x.parentElement) {
          if (x.id) { parts.unshift('#' + CSS.escape(x.id)); break; }
          const twins = x.parentElement ? Array.from(x.parentElement.children).filter((s) => s.tagName === x.tagName) : [];
          parts.unshift(x.tagName.toLowerCase() + (twins.length > 1 ? `:nth-of-type(${twins.indexOf(x) + 1})` : ''));
        }
        return parts.join(' > ');
      };
      const cs = getComputedStyle(el);
      const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || (cs.boxShadow && cs.boxShadow !== 'none');
      return { selector: sel(el), name: (el.getAttribute('aria-label') || el.innerText || el.value || '').trim().slice(0, 80), focusVisible: Boolean(ring && el.matches(':focus-visible')) };
    });
    if (!stop) { if (stops.length) { ended = 'wrapped'; break; } continue; }
    if (first && stop.selector === first) { ended = 'wrapped'; break; }
    first = first || stop.selector;
    stops.push(stop);
  }
  // Note: a ring drawn by a pseudo-element or a colour change is not seen here; such stops show as false and need a look.
  passes.push({ view: `${width}/light/default ${url}`, url, stops, ended });
  await page.close();
}
await browser.close();
fs.mkdirSync(out, { recursive: true });
fs.writeFileSync(path.join(out, 'axe.json'), JSON.stringify({ runs }, null, 1));
fs.writeFileSync(path.join(out, 'keyboard.json'), JSON.stringify({ passes }, null, 1));
console.log(`wrote ${path.join(out, 'axe.json')} and ${path.join(out, 'keyboard.json')}: ${runs.length} page(s)`);
console.log('RESULT pass: scan written; judge it with audit.py check');
