import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";
import type { User } from "../types";
import { ErrorNotice, Loading, Button } from "./ui";
interface Auth {
  user: User | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (p: string) => boolean;
}
const Context = createContext<Auth | null>(null);
export function Session({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const client = useQueryClient();
  useEffect(() => {
    const controller = new AbortController();
    api
      .get<User>("/auth/me", controller.signal)
      .then(setUser)
      .catch((e) => {
        if (!controller.signal.aborted) {
          if (e instanceof ApiError && e.status === 401) setUser(null);
          else setError(e);
        }
      });
    const expired = () => {
      setUser(null);
      void client.cancelQueries();
      client.clear();
    };
    window.addEventListener("session-expired", expired);
    return () => {
      controller.abort();
      window.removeEventListener("session-expired", expired);
    };
  }, [client]);
  if (error)
    return (
      <div className="login-shell">
        <ErrorNotice error={error} />
        <Button onClick={() => window.location.reload()}>
          Reintentar conexión
        </Button>
      </div>
    );
  if (user === undefined) return <Loading />;
  const login = async (email: string, password: string) => {
    await api.post("/auth/login", { email, password });
    const me = await api.get<User>("/auth/me");
    client.clear();
    setUser(me);
  };
  const logout = async () => {
    await api.post("/auth/logout");
    await client.cancelQueries();
    client.clear();
    setUser(null);
  };
  return (
    <Context.Provider
      value={{
        user,
        login,
        logout,
        can: (p) => !!user?.permissions?.includes(p),
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function useSession() {
  const value = useContext(Context);
  if (!value) throw new Error("Sesión no inicializada");
  return value;
}
