import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from "react";

export function cx(...c: (string | false | null | undefined)[]) {
  return c.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";
const variants: Record<Variant, string> = {
  primary: "bg-brand text-white hover:bg-brand-600 disabled:bg-brand/50",
  secondary: "bg-surface text-ink border border-line-strong hover:bg-paper disabled:text-ink-3",
  ghost: "text-ink-2 hover:bg-ink/5 hover:text-ink",
  danger: "bg-surface text-bad border border-bad/30 hover:bg-bad-50 disabled:opacity-50 disabled:hover:bg-surface",
};

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg"; busy?: boolean }
>(function Button({ variant = "primary", size = "md", busy, className, children, disabled, ...p }, ref) {
  const sizes = { sm: "h-8 px-3 text-sm", md: "h-10 px-4 text-sm", lg: "h-12 px-5 text-base" };
  return (
    <button
      ref={ref}
      disabled={disabled || busy}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed",
        sizes[size],
        variants[variant],
        className,
      )}
      {...p}
    >
      {busy && <span className="size-3.5 animate-spin rounded-full border-2 border-current border-r-transparent" />}
      {children}
    </button>
  );
});

export function Field({
  label,
  hint,
  error,
  children,
  id,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  children: (id: string) => ReactNode;
  id?: string;
}) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <div className="space-y-1.5">
      <label htmlFor={fid} className="block text-sm font-medium text-ink">
        {label}
      </label>
      {children(fid)}
      {error ? <p className="text-sm text-bad" data-field-error>{error}</p> : hint ? <p className="text-xs text-ink-3">{hint}</p> : null}
    </div>
  );
}

const inputCls =
  "block w-full rounded-lg border border-line-strong bg-surface px-3 h-10 text-base sm:text-sm text-ink placeholder:text-ink-3 focus:border-brand focus:outline-none focus:ring-2 focus:ring-brand/20 disabled:bg-paper";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...p },
  ref,
) {
  return <input ref={ref} className={cx(inputCls, className)} {...p} />;
});

export function Select({ className, children, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(inputCls, "pr-8", className)} {...p}>
      {children}
    </select>
  );
}

export function Checkbox({ label, hint, ...p }: InputHTMLAttributes<HTMLInputElement> & { label: string; hint?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-3">
      <input type="checkbox" className="mt-0.5 size-4 rounded accent-brand" {...p} />
      <span>
        <span className="block text-sm text-ink">{label}</span>
        {hint && <span className="block text-xs text-ink-3">{hint}</span>}
      </span>
    </label>
  );
}

export function Card({ title, actions, children, className, padded = true }: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={cx("rounded-[var(--radius-card)] border border-line bg-surface", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-5 py-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          <div className="flex items-center gap-2">{actions}</div>
        </header>
      )}
      <div className={padded ? "p-5" : undefined}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-ink-2">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

type Tone = "neutral" | "brand" | "ok" | "warn" | "bad";
export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  const t: Record<Tone, string> = {
    neutral: "bg-ink/5 text-ink-2",
    brand: "bg-brand-50 text-brand",
    ok: "bg-ok-50 text-ok",
    warn: "bg-warn-50 text-warn",
    bad: "bg-bad-50 text-bad",
  };
  return <span className={cx("inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium", t[tone])}>{children}</span>;
}

export function Alert({ tone = "bad", children }: { tone?: "bad" | "ok" | "warn"; children: ReactNode }) {
  const t = { bad: "border-bad/20 bg-bad-50 text-bad", ok: "border-ok/20 bg-ok-50 text-ok", warn: "border-warn/20 bg-warn-50 text-warn" };
  return <div role="alert" className={cx("whitespace-pre-line rounded-lg border px-3 py-2 text-sm", t[tone])}>{children}</div>;
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-6 py-12 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {children && <div className="mt-1 text-sm text-ink-2">{children}</div>}
    </div>
  );
}

export function Dialog({ open, onClose, title, children, footer, wide }: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) {
      d.showModal();
      // showModal() focuses the first focusable element, i.e. the ✕ button; Enter would then
      // close the dialog. Put focus on the first form field instead.
      d.querySelector<HTMLElement>("[data-dialog-body] :is(input:not([type=hidden]), select, textarea)")?.focus();
    }
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onCancel={onClose}
      className={cx(
        "m-auto w-[calc(100%-2rem)] rounded-xl border border-line bg-surface p-0 text-ink shadow-xl backdrop:bg-ink/40",
        wide ? "max-w-3xl" : "max-w-lg",
      )}
    >
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <header className="flex items-center justify-between border-b border-line px-5 py-3">
            <h2 className="font-semibold">{title}</h2>
            <button onClick={onClose} className="rounded p-1 text-ink-3 hover:bg-ink/5 hover:text-ink" aria-label="Close">
              ✕
            </button>
          </header>
          <div data-dialog-body className="overflow-y-auto px-5 py-4">{children}</div>
          {footer && <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
        </div>
      )}
    </dialog>
  );
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-ink-3" role="status">
      <span className="size-4 animate-spin rounded-full border-2 border-ink-3 border-r-transparent" />
      {label}
    </div>
  );
}

export const th = "px-4 py-2.5 text-left text-xs font-medium uppercase tracking-wide text-ink-3";
export const td = "px-4 py-3 text-sm";
