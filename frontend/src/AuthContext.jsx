import { createContext, useCallback, useContext, useEffect, useState } from "react";
import * as api from "./api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!api.getToken()) {
      setLoading(false);
      return;
    }
    api
      .getCurrentUser()
      .then(setUser)
      .catch(() => api.clearToken()) // stale/expired token
      .finally(() => setLoading(false));
  }, []);

  const doLogin = useCallback(async (email, password) => {
    const session = await api.login(email, password);
    api.setTokens(session);
    setUser(await api.getCurrentUser());
  }, []);

  const doRegister = useCallback(async (name, email, password) => {
    const session = await api.register(name, email, password);
    api.setTokens(session);
    setUser(await api.getCurrentUser());
  }, []);

  // Revokes the session server-side, not just locally. That is the whole point of
  // a refresh token: signing out has to end the session, not throw away a copy of
  // it while leaving it valid for anyone who intercepted it.
  const doLogout = useCallback(async () => {
    await api.logout();
    setUser(null);
  }, []);

  const updateProfile = useCallback(async (reviewerType, cuisineSpecialty) => {
    const updated = await api.updateProfile(reviewerType, cuisineSpecialty);
    setUser(updated);
    return updated;
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login: doLogin, register: doRegister, logout: doLogout, updateProfile }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
