import { useState } from "react";
import { useTranslation } from "react-i18next";
import { NavLink, Outlet } from "react-router";
import { LanguageSwitch } from "@/components/LanguageSwitch";
import { cx } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { Wordmark } from "../auth/LoginPage";

const NAV = [
  { to: "/admin", key: "overview", end: true },
  { to: "/admin/visits", key: "visits" },
  { to: "/admin/reports", key: "reports" },
  { to: "/admin/evacuation", key: "evacuation" },
  { to: "/admin/sites", key: "sites" },
  { to: "/admin/people", key: "people" },
  { to: "/admin/form", key: "form" },
  { to: "/admin/invites", key: "invites" },
  { to: "/admin/blacklist", key: "blacklist" },
  { to: "/admin/settings", key: "settings" },
  { to: "/admin/privacy", key: "privacy" },
  { to: "/admin/audit", key: "audit" },
  { to: "/guard", key: "guard" },
] as const;

export default function AdminLayout() {
  const { t } = useTranslation();
  const { me, logout } = useAuth();
  const [open, setOpen] = useState(false);

  const nav = (
    <nav className="space-y-0.5">
      {[...NAV, ...(me?.roles.includes("host") ? [{ to: "/admin/my-visitors", key: "host" }] : [])].map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          end={"end" in n}
          onClick={() => setOpen(false)}
          className={({ isActive }) =>
            cx(
              "block rounded-md px-3 py-2 text-sm",
              isActive ? "bg-brand-50 font-medium text-brand" : "text-ink-2 hover:bg-ink/5 hover:text-ink",
            )
          }
        >
          {t(`nav.${n.key}`)}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[232px_minmax(0,1fr)]">
      <aside className="hidden border-r border-line bg-surface lg:flex lg:flex-col">
        <div className="px-5 py-5"><Wordmark /></div>
        <div className="px-3 pb-3">
          <p className="truncate px-3 pb-3 text-xs font-medium uppercase tracking-wide text-ink-3">{me?.org?.name}</p>
          {nav}
        </div>
        <div className="mt-auto space-y-3 border-t border-line p-4">
          <LanguageSwitch />
          <div className="text-sm">
            <p className="truncate font-medium">{me?.full_name}</p>
            <button onClick={() => void logout()} className="text-ink-3 hover:text-ink">{t("auth.signOut")}</button>
          </div>
        </div>
      </aside>

      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-surface px-4 py-3 lg:hidden">
        <Wordmark />
        <button onClick={() => setOpen(!open)} className="rounded-md border border-line px-3 py-1.5 text-sm" aria-expanded={open}>
          {t("nav.menu")}
        </button>
      </header>
      {open && (
        <div className="border-b border-line bg-surface p-3 lg:hidden">
          {nav}
          <div className="mt-3 flex items-center justify-between border-t border-line pt-3">
            <LanguageSwitch />
            <button onClick={() => void logout()} className="text-sm text-ink-2">{t("auth.signOut")}</button>
          </div>
        </div>
      )}

      <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-8 sm:py-8">
        <Outlet />
      </main>
    </div>
  );
}
