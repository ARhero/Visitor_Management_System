import i18n from "i18next";
import { initReactI18next } from "react-i18next";
// Adding a language: docs/adding-a-language.md. Translation files are picked up by
// name (see below); list the language here.
export const LANGUAGES = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
] as const;

const saved = (() => {
  try {
    return localStorage.getItem("vms.lang");
  } catch {
    return null;
  }
})();

/**
 * Translations load on demand, one file per language and screen group, so a visitor
 * downloads only their own language's strings:
 *   locales/<code>.json         sign-in, navigation    (namespace "translation")
 *   locales/visit.<code>.json   public pages            (namespace "visit")
 *   locales/visitmore.<code>.json  privacy page, host answer page ("visitmore"; kept out
 *                               of the visitor's first load)
 *   locales/staff.<code>.json   guard and host screens  (namespace "staff")
 * useTranslation(ns) suspends until its file is in, so pages render inside <Suspense>.
 * There is no fallback language: tests guarantee every file has every key.
 */
const files = import.meta.glob<Record<string, unknown>>("../locales/*.json", { import: "default" });

const lazyFiles = {
  type: "backend" as const,
  init() {},
  read(lng: string, ns: string, done: (err: unknown, data?: Record<string, unknown>) => void) {
    const load = files[`../locales/${ns === "translation" ? "" : `${ns}.`}${lng}.json`];
    if (!load) return done(null, {});
    load().then((d) => done(null, d), (e) => done(e));
  },
};

void i18n.use(lazyFiles).use(initReactI18next).init({
  lng: saved ?? "en",
  supportedLngs: LANGUAGES.map((l) => l.code),
  fallbackLng: false,
  ns: ["translation"],
  interpolation: { escapeValue: false },
});

i18n.on("languageChanged", (lng) => {
  document.documentElement.lang = lng;
  try {
    localStorage.setItem("vms.lang", lng);
  } catch {
    /* private mode */
  }
});

export default i18n;

/** Set when a person picks a language themselves; until then pages may apply a default
 *  (e.g. the visitor check-in uses the organization's default language). */
export function markLanguageChosen() {
  try {
    localStorage.setItem("vms.langChosen", "1");
  } catch {
    /* private mode */
  }
}
export function languageChosen(): boolean {
  try {
    return localStorage.getItem("vms.langChosen") === "1";
  } catch {
    return false;
  }
}
