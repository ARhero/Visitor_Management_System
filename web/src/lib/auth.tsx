import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, refreshSession, setAccessToken, setOnSessionLost } from "./api";
import type { Me } from "./types";

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (identifier: string, password: string, orgSlug?: string) => Promise<void>;
  acceptToken: (token: string) => Promise<void>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const qc = useQueryClient();

  const loadMe = useCallback(async () => setMe(await api<Me>("/auth/me")), []);

  useEffect(() => {
    setOnSessionLost(() => {
      setMe(null);
      qc.clear();
    });
    // Restore the session from the refresh cookie on first load.
    (async () => {
      try {
        if (await refreshSession()) await loadMe();
      } finally {
        setLoading(false);
      }
    })();
  }, [loadMe, qc]);

  const acceptToken = useCallback(
    async (token: string) => {
      setAccessToken(token);
      await loadMe();
    },
    [loadMe],
  );

  const login = useCallback(
    async (identifier: string, password: string, orgSlug?: string) => {
      const r = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: { identifier, password, org_slug: orgSlug || undefined },
      });
      await acceptToken(r.access_token);
    },
    [acceptToken],
  );

  const logout = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } finally {
      try {
        // The guard console's offline pass lists (today's visitor names) go too.
        for (const k of Object.keys(sessionStorage)) if (k.startsWith("vms.pack.")) sessionStorage.removeItem(k);
      } catch {
        /* nothing stored */
      }
      setAccessToken(null);
      setMe(null);
      qc.clear();
    }
  }, [qc]);

  return <Ctx.Provider value={{ me, loading, login, acceptToken, logout }}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function homeFor(me: Me): string {
  if (me.roles.includes("super_admin")) return "/platform";
  if (me.roles.includes("org_admin")) return "/admin";
  if (me.roles.includes("guard")) return "/guard";
  return "/host";
}
