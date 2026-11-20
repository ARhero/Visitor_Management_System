import { useTranslation } from "react-i18next";
import { LANGUAGES, markLanguageChosen } from "@/lib/i18n";
import { cx } from "./ui";

export function LanguageSwitch({ className }: { className?: string }) {
  const { i18n, t } = useTranslation();
  return (
    <div role="group" aria-label={t("common.language")} className={cx("inline-flex rounded-lg border border-line bg-surface p-0.5", className)}>
      {LANGUAGES.map((l) => (
        <button
          key={l.code}
          type="button"
          onClick={() => { markLanguageChosen(); void i18n.changeLanguage(l.code); }}
          aria-pressed={i18n.language === l.code}
          className={cx(
            "rounded-md px-2.5 py-1 text-xs font-medium",
            i18n.language === l.code ? "bg-brand text-white" : "text-ink-2 hover:text-ink",
          )}
        >
          {l.label}
        </button>
      ))}
    </div>
  );
}
