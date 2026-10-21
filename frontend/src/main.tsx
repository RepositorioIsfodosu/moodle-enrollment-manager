import React, { Component, lazy, Suspense, type ReactNode } from "react";
import ReactDOM from "react-dom/client";
import {
  BrowserRouter,
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";
import "./styles.css";
import { ApiError } from "./api/client";
import { Session, useSession } from "./components/session";
import { Layout } from "./components/layout";
const Login = lazy(() =>
  import("./pages/login").then((m) => ({ default: m.Login })),
);
const Dashboard = lazy(() =>
  import("./pages/dashboard").then((m) => ({ default: m.Dashboard })),
);
const Reports = lazy(() =>
  import("./pages/reports").then((m) => ({ default: m.Reports })),
);
const Jobs = lazy(() =>
  import("./pages/jobs").then((m) => ({ default: m.Jobs })),
);
const JobDetail = lazy(() =>
  import("./pages/jobs").then((m) => ({ default: m.JobDetail })),
);
const Errors = lazy(() =>
  import("./pages/jobs").then((m) => ({ default: m.Errors })),
);
const Files = lazy(() =>
  import("./pages/imports").then((m) => ({ default: m.Files })),
);
const FileDetail = lazy(() =>
  import("./pages/imports").then((m) => ({ default: m.FileDetail })),
);
const NewEnrollment = lazy(() =>
  import("./pages/imports").then((m) => ({ default: m.NewEnrollment })),
);
const ValidationDetail = lazy(() =>
  import("./pages/imports").then((m) => ({ default: m.ValidationDetail })),
);
const Connections = lazy(() =>
  import("./pages/connections").then((m) => ({ default: m.Connections })),
);
const Users = lazy(() =>
  import("./pages/administration").then((m) => ({ default: m.Users })),
);
const AuditLog = lazy(() =>
  import("./pages/administration").then((m) => ({ default: m.AuditLog })),
);
const Settings = lazy(() =>
  import("./pages/administration").then((m) => ({ default: m.Settings })),
);
import { Loading, Empty } from "./components/ui";
const client = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10000,
      retry: (count, error) =>
        count < 1 &&
        (!(error instanceof ApiError) ||
          error.status === 0 ||
          error.status >= 500),
      refetchOnWindowFocus: true,
    },
    mutations: { retry: false },
  },
});
function Guard({
  permission,
  children,
}: {
  permission?: string;
  children: ReactNode;
}) {
  const { user, can } = useSession();
  const location = useLocation();
  if (!user)
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  if (permission && !can(permission))
    return (
      <Empty title="No tienes acceso a esta sección">
        Consulta con el administrador si necesitas otros permisos.{" "}
        <Link to="/">Volver al inicio</Link>
      </Empty>
    );
  return children;
}
class ErrorBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? (
      <div className="login-shell">
        <div>
          <h1>No se pudo mostrar la página</h1>
          <p>Recarga para recuperar el estado guardado en el servidor.</p>
          <button
            className="btn btn-primary"
            onClick={() => window.location.reload()}
          >
            Recargar
          </button>
        </div>
      </div>
    ) : (
      this.props.children
    );
  }
}
function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Guard>
            <Layout />
          </Guard>
        }
      >
        <Route index element={<Dashboard />} />
        <Route
          path="new"
          element={
            <Guard permission="imports:write">
              <NewEnrollment />
            </Guard>
          }
        />
        <Route
          path="files"
          element={
            <Guard permission="imports:read">
              <Files />
            </Guard>
          }
        />
        <Route
          path="files/:id"
          element={
            <Guard permission="imports:read">
              <FileDetail />
            </Guard>
          }
        />
        <Route path="validations/:id" element={<ValidationDetail />} />
        <Route path="jobs" element={<Jobs />} />
        <Route path="jobs/:id" element={<JobDetail />} />
        <Route path="history" element={<Jobs history />} />
        <Route path="errors" element={<Errors />} />
        <Route
          path="reports"
          element={
            <Guard permission="reports:read">
              <Reports />
            </Guard>
          }
        />
        <Route
          path="connections"
          element={
            <Guard permission="connections:manage">
              <Connections />
            </Guard>
          }
        />
        <Route
          path="users"
          element={
            <Guard permission="users:manage">
              <Users />
            </Guard>
          }
        />
        <Route
          path="audit"
          element={
            <Guard permission="audit:read">
              <AuditLog />
            </Guard>
          }
        />
        <Route path="settings" element={<Settings />} />
        <Route
          path="*"
          element={
            <Empty title="Página no encontrada">
              <Link to="/">Volver al inicio</Link>
            </Empty>
          }
        />
      </Route>
    </Routes>
  );
}
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={client}>
        <BrowserRouter>
          <Session>
            <Suspense fallback={<Loading />}>
              <App />
            </Suspense>
          </Session>
        </BrowserRouter>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
