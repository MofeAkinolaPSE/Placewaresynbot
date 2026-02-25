import { PropsWithChildren, createContext, useContext, useEffect, useMemo, useState } from "react";
import { authClient } from "@/lib/auth-client";

type AuthContextValue = {
  isAuthenticated: boolean;
  isLoading: boolean;
  roles: string[];
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<boolean>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export const useAuth = (): AuthContextValue => {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
};

const AuthProvider = ({ children }: PropsWithChildren) => {
  const [isLoading, setIsLoading] = useState(true);
  const [isAuthenticated, setIsAuthenticated] = useState(authClient.isAuthenticated());
  const [roles, setRoles] = useState<string[]>(authClient.getRoles());

  useEffect(() => {
    let active = true;
    (async () => {
      const ok = await authClient.refresh();
      if (!active) return;
      setIsAuthenticated(ok || authClient.isAuthenticated());
      setRoles(authClient.getRoles());
      setIsLoading(false);
    })();

    const onAuthExpired = () => {
      if (!active) return;
      setIsAuthenticated(false);
    };
    window.addEventListener("auth:expired", onAuthExpired as EventListener);

    return () => {
      active = false;
      window.removeEventListener("auth:expired", onAuthExpired as EventListener);
    };
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      isAuthenticated,
      isLoading,
      login: async (email: string, password: string) => {
        await authClient.login(email, password);
        setIsAuthenticated(true);
        setRoles(authClient.getRoles());
      },
      logout: async () => {
        await authClient.logout();
        setIsAuthenticated(false);
        setRoles([]);
      },
      refresh: async () => {
        const ok = await authClient.refresh();
        setIsAuthenticated(ok || authClient.isAuthenticated());
        setRoles(authClient.getRoles());
        return ok;
      },
      roles,
    }),
    [isAuthenticated, isLoading, roles],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export default AuthProvider;
