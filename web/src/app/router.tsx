import { lazy, Suspense, type ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router";
import { Spinner } from "@/components/ui";

/**
 * Two halves, so a visitor's phone downloads as little as possible:
 * - Public pages (QR check-in, pass, visit status, host's WhatsApp link, privacy page)
 *   are routed here and need no session or data cache.
 * - Everything for staff (sign-in, admin, gate console, host app, platform console) is
 *   one lazy `StaffApp` that brings its own providers (session, React Query).
 * Each page is its own chunk on top of that.
 */
const CheckinPage = lazy(() => import("@/features/visitor/CheckinPage"));
const VisitStatusPage = lazy(() => import("@/features/visitor/VisitStatusPage"));
const PassPage = lazy(() => import("@/features/visitor/PassPage"));
const RespondPage = lazy(() => import("@/features/visitor/RespondPage"));
const PrivacyPortal = lazy(() => import("@/features/visitor/PrivacyPortal"));
const EvacuationLinkPage = lazy(() => import("@/features/visitor/EvacuationLinkPage"));
const StaffApp = lazy(() => import("./StaffApp"));

const S = ({ children }: { children: ReactNode }) => <Suspense fallback={<Spinner />}>{children}</Suspense>;

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/v/:gateToken" element={<S><CheckinPage /></S>} />
        <Route path="/visit/:visitId" element={<S><VisitStatusPage /></S>} />
        <Route path="/p/:passToken" element={<S><PassPage /></S>} />
        <Route path="/r/:token" element={<S><RespondPage /></S>} />
        <Route path="/privacy/:slug" element={<S><PrivacyPortal /></S>} />
        <Route path="/e/:token" element={<S><EvacuationLinkPage /></S>} />
        <Route path="/*" element={<S><StaffApp /></S>} />
      </Routes>
    </BrowserRouter>
  );
}
