import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Outlet, Route, Routes } from "react-router";
import { Spinner } from "@/components/ui";
import { AuthProvider, homeFor, useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";

// Each staff area is its own chunk, so the guard console never downloads admin code.
const LoginPage = lazy(() => import("@/features/auth/LoginPage"));
const SignupPage = lazy(() => import("@/features/auth/SignupPage"));
const MagicLinkPage = lazy(() => import("@/features/auth/MagicLinkPage"));
const AdminLayout = lazy(() => import("@/features/admin/AdminLayout"));
const DashboardPage = lazy(() => import("@/features/admin/DashboardPage"));
const SetupWizard = lazy(() => import("@/features/admin/SetupWizard"));
const VisitsPage = lazy(() => import("@/features/admin/VisitsPage"));
const ReportsPage = lazy(() => import("@/features/admin/ReportsPage"));
const EvacuationPage = lazy(() => import("@/features/admin/EvacuationPage"));
const SitesPage = lazy(() => import("@/features/admin/SitesPage"));
const PeoplePage = lazy(() => import("@/features/admin/PeoplePage"));
const FormConfigPage = lazy(() => import("@/features/admin/FormConfigPage"));
const SettingsPage = lazy(() => import("@/features/admin/SettingsPage"));
const AuditPage = lazy(() => import("@/features/admin/AuditPage"));
const InvitesPage = lazy(() => import("@/features/admin/InvitesPage"));
const BlacklistPage = lazy(() => import("@/features/admin/BlacklistPage"));
const PrivacyPage = lazy(() => import("@/features/admin/PrivacyPage"));
const MyVisitorsPage = lazy(() => import("@/features/admin/MyVisitorsPage"));
const GuardApp = lazy(() => import("@/features/guard/GuardApp"));
const HostApp = lazy(() => import("@/features/host/HostApp"));
const PlatformApp = lazy(() => import("@/features/platform/PlatformApp"));
const PlatformLogin = lazy(() => import("@/features/platform/PlatformApp").then((m) => ({ default: m.PlatformLogin })));
const DevWhatsAppPage = lazy(() => import("@/features/dev/DevWhatsAppPage"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: (n, e) => n < 2 && !(e instanceof Error && "status" in e && (e as { status: number }).status < 500) },
  },
});

const S = ({ children }: { children: ReactNode }) => <Suspense fallback={<Spinner />}>{children}</Suspense>;

function RequireRole({ roles, login = "/login" }: { roles: (Role | "super_admin")[]; login?: string }) {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  if (!me) return <Navigate to={login} replace />;
  if (!me.roles.some((r) => (roles as string[]).includes(r))) return <Navigate to={homeFor(me)} replace />;
  return <Outlet />;
}

function Home() {
  const { me, loading } = useAuth();
  if (loading) return <Spinner />;
  return <Navigate to={me ? homeFor(me) : "/login"} replace />;
}

export default function StaffApp() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/login" element={<S><LoginPage /></S>} />
          <Route path="/signup" element={<S><SignupPage /></S>} />
          <Route path="/m/:token" element={<S><MagicLinkPage /></S>} />
          <Route path="/platform/login" element={<S><PlatformLogin /></S>} />
          <Route path="/dev/whatsapp" element={<S><DevWhatsAppPage /></S>} />
          <Route element={<RequireRole roles={["org_admin"]} />}>
            <Route path="/admin" element={<S><AdminLayout /></S>}>
              <Route index element={<S><DashboardPage /></S>} />
              <Route path="setup" element={<S><SetupWizard /></S>} />
              <Route path="visits" element={<S><VisitsPage /></S>} />
              <Route path="reports" element={<S><ReportsPage /></S>} />
              <Route path="evacuation" element={<S><EvacuationPage /></S>} />
              <Route path="sites" element={<S><SitesPage /></S>} />
              <Route path="people" element={<S><PeoplePage /></S>} />
              <Route path="form" element={<S><FormConfigPage /></S>} />
              <Route path="invites" element={<S><InvitesPage /></S>} />
              <Route path="blacklist" element={<S><BlacklistPage /></S>} />
              <Route path="settings" element={<S><SettingsPage /></S>} />
              <Route path="audit" element={<S><AuditPage /></S>} />
              <Route path="privacy" element={<S><PrivacyPage /></S>} />
              <Route path="my-visitors" element={<S><MyVisitorsPage /></S>} />
            </Route>
          </Route>
          {/* Admins can stand in at the gate too. */}
          <Route element={<RequireRole roles={["guard", "org_admin"]} />}>
            <Route path="/guard" element={<S><GuardApp /></S>} />
          </Route>
          <Route element={<RequireRole roles={["host"]} />}>
            <Route path="/host" element={<S><HostApp /></S>} />
          </Route>
          <Route element={<RequireRole roles={["super_admin"]} login="/platform/login" />}>
            <Route path="/platform" element={<S><PlatformApp /></S>} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </QueryClientProvider>
  );
}
