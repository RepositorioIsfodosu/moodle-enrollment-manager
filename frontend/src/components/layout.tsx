import { createContext, useContext, useState } from "react";
import { NavLink, Outlet, Link, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  Bell,
  BookOpen,
  ChartNoAxesCombined,
  ChevronDown,
  CircleHelp,
  ClipboardList,
  FileSpreadsheet,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Plug,
  Plus,
  Settings,
  ShieldAlert,
  Users,
  X,
} from "lucide-react";
import { api } from "../api/client";
import type { Destination, Operation, Page } from "../types";
import { Badge, ErrorNotice, formatDate } from "./ui";
import { useSession } from "./session";
interface Scope {
  connection: string;
  setConnection: (id: string) => void;
  destinations: Destination[];
}
const Context = createContext<Scope>({
  connection: "",
  setConnection: () => {},
  destinations: [],
});
export function useScope() {
  return useContext(Context);
}
const links = [
  { to: "/", name: "Dashboard", icon: LayoutDashboard, p: "jobs:read" },
  { to: "/new", name: "Nueva matriculación", icon: Plus, p: "imports:write" },
  {
    to: "/files",
    name: "Archivos CSV",
    icon: FileSpreadsheet,
    p: "imports:read",
  },
  { to: "/jobs", name: "Procesos", icon: ClipboardList, p: "jobs:read" },
  { to: "/history", name: "Historial", icon: History, p: "jobs:read" },
  { to: "/errors", name: "Errores", icon: ShieldAlert, p: "jobs:read" },
  {
    to: "/reports",
    name: "Reportes",
    icon: ChartNoAxesCombined,
    p: "reports:read",
  },
  {
    to: "/connections",
    name: "Conexiones Moodle",
    icon: Plug,
    p: "connections:manage",
  },
  { to: "/users", name: "Usuarios y permisos", icon: Users, p: "users:manage" },
  { to: "/audit", name: "Auditoría", icon: BookOpen, p: "audit:read" },
  { to: "/settings", name: "Configuración", icon: Settings, p: "" },
];
export function Layout() {
  const { user, can, logout } = useSession();
  const [connection, setConnection] = useState("");
  const [menu, setMenu] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const location = useLocation();
  const destinations = useQuery({
    queryKey: ["destinations"],
    queryFn: ({ signal }) =>
      api.get<Page<Destination>>("/validations/connections", signal),
    refetchInterval: 30000,
  });
  const incidents = useQuery({
    queryKey: ["notifications", connection],
    queryFn: ({ signal }) =>
      api.get<Page<Operation>>(
        "/enrollment-records?limit=5" +
          (connection ? "&connection_id=" + connection : ""),
        signal,
      ),
    refetchInterval: 15000,
  });
  const current = destinations.data?.items.find((d) => d.id === connection);
  const section =
    links.find((l) =>
      l.to === "/"
        ? location.pathname === "/"
        : location.pathname.startsWith(l.to),
    )?.name || "Detalle del proceso";
  return (
    <Context.Provider
      value={{
        connection,
        setConnection,
        destinations: destinations.data?.items || [],
      }}
    >
      <a className="skip-link" href="#main">
        Saltar al contenido
      </a>
      <div className="app-shell">
        <aside className={"sidebar " + (menu ? "sidebar-open" : "")}>
          <Link className="brand" to="/">
            <span className="brand-mark">M</span>
            <span>
              Enrollment<span className="brand-sub">MANAGER</span>
            </span>
          </Link>
          <button
            className="icon-btn mobile-only sidebar-close"
            onClick={() => setMenu(false)}
            aria-label="Cerrar menú"
          >
            <X size={20} />
          </button>
          <div className="nav-caption">ESPACIO DE TRABAJO</div>
          <nav aria-label="Navegación principal">
            {links
              .filter((l) => !l.p || can(l.p))
              .map((l) => (
                <NavLink
                  end={l.to === "/"}
                  key={l.to}
                  to={l.to}
                  onClick={() => setMenu(false)}
                >
                  <l.icon size={18} />
                  {l.name}
                </NavLink>
              ))}
          </nav>
          <div className="sidebar-bottom">
            <CircleHelp size={17} />
            <div>
              <strong>Control y trazabilidad</strong>
              <span>America / Santo Domingo</span>
            </div>
            <ArrowUpRight size={14} />
          </div>
        </aside>
        {menu && (
          <button
            className="scrim"
            onClick={() => setMenu(false)}
            aria-label="Cerrar navegación"
          />
        )}
        <div className="workspace">
          <header className="topbar">
            <div className="topbar-left">
              <button
                className="icon-btn mobile-only"
                onClick={() => setMenu(true)}
                aria-label="Abrir menú"
              >
                <Menu size={20} />
              </button>
              <span className="section-name">{section}</span>
            </div>
            <div className="topbar-right">
              <div className="destination-select">
                <Plug size={15} />
                <select
                  aria-label="Moodle seleccionado"
                  value={connection}
                  onChange={(e) => setConnection(e.target.value)}
                >
                  <option value="">Todas las instalaciones</option>
                  {destinations.data?.items.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name}
                    </option>
                  ))}
                </select>
                <ChevronDown size={13} />
              </div>
              {current && (
                <span
                  className="destination-status"
                  title={
                    "Última comprobación: " +
                    formatDate(current.last_verified_at)
                  }
                >
                  <Badge state={current.status} />
                </span>
              )}
              <div className="notifications">
                <button
                  className="icon-btn"
                  aria-label="Notificaciones de incidencias"
                  aria-expanded={notifications}
                  onClick={() => setNotifications(!notifications)}
                >
                  <Bell size={19} />
                  {!!incidents.data?.total && (
                    <span className="notification-dot" />
                  )}
                </button>
                {notifications && (
                  <div className="notification-panel">
                    <strong>Incidencias recientes</strong>
                    <ErrorNotice error={incidents.error} />
                    {incidents.data?.items.length ? (
                      incidents.data.items.map((r) => (
                        <Link
                          key={r.id}
                          to={"/jobs/" + r.job_id}
                          onClick={() => setNotifications(false)}
                        >
                          <Badge state={r.state || "failed"} />
                          <span>
                            {r.job_name}
                            <small>{r.error_code}</small>
                          </span>
                        </Link>
                      ))
                    ) : (
                      <p>No hay incidencias disponibles.</p>
                    )}
                  </div>
                )}
              </div>
              <div className="user-chip">
                <span className="avatar">
                  {user?.email.slice(0, 1).toUpperCase()}
                </span>
                <div>
                  <strong>{user?.email}</strong>
                  <small>{user?.roles.join(", ")}</small>
                </div>
              </div>
              <button
                className="icon-btn"
                aria-label="Cerrar sesión"
                onClick={() => {
                  void logout().catch(setError);
                }}
              >
                <LogOut size={17} />
              </button>
            </div>
          </header>
          <main id="main">
            <ErrorNotice error={destinations.error} />
            <ErrorNotice error={error} />
            <Outlet />
          </main>
          <footer className="workspace-footer">
            <span>Moodle Enrollment Manager</span>
            <span>Procesos persistentes · Datos comprobables</span>
          </footer>
        </div>
      </div>
    </Context.Provider>
  );
}
