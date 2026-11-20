import type { ReactNode } from "react";
import { LanguageSwitch } from "@/components/LanguageSwitch";

/** Phone-first frame for visitor / host-link / pass pages: org name, language, one column. */
export function PublicShell({ org, sub, color, logo, children }: { org?: string; sub?: string; color?: string; logo?: string | null; children: ReactNode }) {
  return (
    <div className="min-h-dvh bg-paper">
      <div className="h-1.5" style={{ background: color || "var(--color-brand)" }} />
      <header className="mx-auto flex max-w-md items-start justify-between gap-3 px-4 pt-4 pb-2">
        <div className="flex min-w-0 items-center gap-3">
          {logo && <img src={logo} alt="" className="size-10 shrink-0 rounded-md object-contain" />}
          <div className="min-w-0">
            <p className="truncate text-base font-semibold">{org ?? " "}</p>
            {sub && <p className="truncate text-sm text-ink-2">{sub}</p>}
          </div>
        </div>
        <LanguageSwitch className="shrink-0" />
      </header>
      <main className="mx-auto max-w-md px-4 pt-2 pb-10">{children}</main>
    </div>
  );
}

/** Text with its web links made tappable (privacy notices end with the privacy page link). */
export function Linkified({ text }: { text: string }) {
  const parts = text.split(/(https?:\/\/[^\s)]+)/g);
  return <>{parts.map((p, i) => (i % 2 ? <a key={i} href={p} target="_blank" rel="noreferrer" className="break-all text-brand underline">{p.replace(/^https?:\/\//, "")}</a> : p))}</>;
}

export function Panel({ children }: { children: ReactNode }) {
  return <div className="rounded-[var(--radius-card)] border border-line bg-surface p-5 shadow-sm">{children}</div>;
}

export function BigButton({ children, ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean }) {
  const { busy, disabled, className, ...rest } = p;
  return (
    <button
      disabled={disabled || busy}
      className={`flex h-12 w-full items-center justify-center gap-2 rounded-xl bg-brand text-base font-medium text-white hover:bg-brand-600 disabled:bg-brand/50 ${className ?? ""}`}
      {...rest}
    >
      {busy && <span className="size-4 animate-spin rounded-full border-2 border-current border-r-transparent" />}
      {children}
    </button>
  );
}
