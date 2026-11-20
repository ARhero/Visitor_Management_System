import { describe, expect, it } from "vitest";
import { LANGUAGES } from "@/lib/i18n";

/** Every language must have every string, with the same {{placeholders}}. This is the
 *  check to run after adding a language (docs/adding-a-language.md). */

const files = import.meta.glob<Record<string, unknown>>("./*.json", { eager: true, import: "default" });
const NAMESPACES = ["", "staff.", "visit.", "visitmore."]; // en.json, staff.en.json, visit.en.json...

function flatten(o: unknown, prefix = ""): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(o as Record<string, unknown>)) {
    const key = prefix ? `${prefix}.${k}` : k;
    if (v && typeof v === "object" && !Array.isArray(v)) Object.assign(out, flatten(v, key));
    else out[key] = String(v);
  }
  return out;
}
const vars = (s: string) => [...s.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map((m) => m[1]).sort().join(",");

describe.each(NAMESPACES)("locale files %s*.json", (ns) => {
  const base = flatten(files[`./${ns}en.json`]);
  it.each(LANGUAGES.map((l) => l.code).filter((c) => c !== "en"))("%s has the same keys and placeholders as English", (code) => {
    const file = files[`./${ns}${code}.json`];
    expect(file, `missing src/locales/${ns}${code}.json`).toBeTruthy();
    const other = flatten(file);
    expect(Object.keys(other).sort()).toEqual(Object.keys(base).sort());
    for (const [k, v] of Object.entries(base)) {
      expect(vars(other[k]), `${ns}${code}.json ${k}`).toBe(vars(v));
      expect(other[k].trim(), `${ns}${code}.json ${k} is empty`).not.toBe("");
    }
  });
});
