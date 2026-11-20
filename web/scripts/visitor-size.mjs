// Fails if a visitor's first load (QR check-in page: entry + page chunks + CSS + their
// language's strings) is over the budget. Run after `vite build --manifest`:
//   npm run size
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";
import { join } from "node:path";

const BUDGET_KB = 120;
const dist = "dist";
const m = JSON.parse(readFileSync(join(dist, ".vite/manifest.json"), "utf8"));
const find = (s) => (m[s] ? s : Object.keys(m).find((k) => k.includes(s)));

function firstLoad(extra) {
  const seen = new Set();
  const walk = (k) => {
    if (!k || seen.has(k)) return;
    seen.add(k);
    for (const i of m[k].imports ?? []) walk(i);
  };
  walk(Object.keys(m).find((k) => m[k].isEntry));
  for (const s of extra) walk(find(s));
  const files = new Set(["index.html"]);
  for (const k of seen) {
    files.add(m[k].file);
    for (const c of m[k].css ?? []) files.add(c);
  }
  let bytes = 0;
  for (const f of files) bytes += gzipSync(readFileSync(join(dist, f)), { level: 9 }).length;
  return bytes / 1024;
}

let failed = false;
for (const lang of ["en", "hi"]) {
  const kb = firstLoad(["CheckinPage", `src/locales/${lang}.json`, `src/locales/visit.${lang}.json`]);
  const ok = kb <= BUDGET_KB;
  failed ||= !ok;
  console.log(`${ok ? "ok  " : "OVER"} visitor first load (${lang}): ${kb.toFixed(1)} KB gz (budget ${BUDGET_KB})`);
}
process.exit(failed ? 1 : 0);
