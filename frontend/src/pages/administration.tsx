import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus } from "lucide-react";
import { api, query } from "../api/client";
import type { Audit, Page, Settings as SettingsType, User } from "../types";
import { useSession } from "../components/session";
import {
  Badge,
  Button,
  Empty,
  ErrorNotice,
  Field,
  formatDate,
  Loading,
  Modal,
  Notice,
  number,
  PageTitle,
  Pagination,
  Panel,
} from "../components/ui";
export function Users() {
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [edit, setEdit] = useState<User | null | undefined>(undefined);
  const [password, setPassword] = useState<User | null>(null);
  const data = useQuery({
    queryKey: ["users", search, offset],
    queryFn: ({ signal }) =>
      api.get<Page<User>>(
        "/users" + query({ search, offset, limit: 25 }),
        signal,
      ),
  });
  useEffect(() => setOffset(0), [search]);
  return (
    <>
      <PageTitle
        title="Usuarios y permisos"
        description="Controla el acceso a la aplicación y los roles de cada cuenta."
        action={
          <Button onClick={() => setEdit(null)}>
            <Plus size={16} />
            Nuevo usuario
          </Button>
        }
      />
      <Panel>
        <div className="toolbar">
          <Field label="Buscar por correo">
            <input
              type="search"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </Field>
        </div>
        <ErrorNotice error={data.error} />
        {data.isPending ? (
          <Loading />
        ) : data.data?.items.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Correo</th>
                  <th>Roles</th>
                  <th>Estado</th>
                  <th>Creado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {data.data.items.map((u) => (
                  <tr key={u.id}>
                    <td>{u.email}</td>
                    <td>{u.roles.join(", ")}</td>
                    <td>
                      <Badge state={u.active ? "valid" : "disabled"} />
                    </td>
                    <td>{formatDate(u.created_at)}</td>
                    <td>
                      <div className="actions">
                        <Button
                          variant="ghost"
                          onClick={() => setEdit(u)}
                          aria-label={"Editar " + u.email}
                        >
                          <Pencil size={16} />
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => setPassword(u)}
                          aria-label={"Restablecer contraseña de " + u.email}
                        >
                          <KeyRound size={16} />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty />
        )}
        <Pagination
          offset={offset}
          total={data.data?.total || 0}
          limit={25}
          onChange={setOffset}
        />
      </Panel>
      {edit !== undefined && (
        <UserForm initial={edit} onClose={() => setEdit(undefined)} />
      )}{" "}
      {password && (
        <ResetPassword user={password} onClose={() => setPassword(null)} />
      )}
    </>
  );
}
function UserForm({
  initial,
  onClose,
}: {
  initial: User | null;
  onClose: () => void;
}) {
  const [roles, setRoles] = useState(initial?.roles || ["consulta"]);
  const [error, setError] = useState<unknown>(null);
  const client = useQueryClient();
  const data = useQuery({
    queryKey: ["roles"],
    queryFn: ({ signal }) =>
      api.get<{ name: string; permissions: string[] }[]>("/roles", signal),
  });
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<{ email: string; password: string; active: boolean }>({
    defaultValues: {
      email: initial?.email || "",
      active: initial?.active ?? true,
    },
  });
  return (
    <Modal
      title={initial ? "Editar usuario" : "Crear usuario"}
      onClose={isSubmitting ? () => {} : onClose}
    >
      <form
        onSubmit={handleSubmit(async (v) => {
          setError(null);
          if (!roles.length) {
            setError(new Error("Selecciona al menos un rol."));
            return;
          }
          try {
            if (initial)
              await api.patch("/users/" + initial.id, {
                roles,
                active: v.active,
              });
            else
              await api.post("/users", {
                email: v.email,
                password: v.password,
                roles,
              });
            await client.invalidateQueries();
            onClose();
          } catch (e) {
            setError(e);
          }
        })}
      >
        <Field label="Correo electrónico">
          <input
            type="email"
            required
            readOnly={!!initial}
            maxLength={320}
            {...register("email")}
          />
        </Field>
        {!initial && (
          <Field
            label="Contraseña inicial"
            hint="Entre 12 y 128 caracteres. Comunícala por un medio seguro."
          >
            <input
              type="password"
              autoComplete="new-password"
              required
              minLength={12}
              maxLength={128}
              {...register("password")}
            />
          </Field>
        )}
        <fieldset>
          <legend>Roles de la aplicación</legend>
          {data.data?.map((r) => (
            <label className="check-field" key={r.name}>
              <input
                type="checkbox"
                checked={roles.includes(r.name)}
                onChange={(e) =>
                  setRoles((previous) =>
                    e.target.checked
                      ? [...previous, r.name]
                      : previous.filter((n) => n !== r.name),
                  )
                }
              />
              <span>
                {r.name}
                <small className="role-permissions">
                  {r.permissions.join(" · ")}
                </small>
              </span>
            </label>
          ))}
        </fieldset>
        {initial && (
          <label className="check-field">
            <input type="checkbox" {...register("active")} />
            Cuenta activa
          </label>
        )}
        <Notice>
          Los cambios revocan las sesiones del usuario. El servidor impide
          eliminar el último administrador activo.
        </Notice>
        <ErrorNotice error={error || data.error} />
        <div className="actions">
          <Button
            variant="secondary"
            type="button"
            disabled={isSubmitting}
            onClick={onClose}
          >
            Volver
          </Button>
          <Button type="submit" busy={isSubmitting}>
            Guardar usuario
          </Button>
        </div>
      </form>
    </Modal>
  );
}
function ResetPassword({ user, onClose }: { user: User; onClose: () => void }) {
  const [password, setPassword] = useState("");
  const client = useQueryClient();
  const action = useMutation({
    mutationFn: () =>
      api.post(`/users/${user.id}/reset-password`, { new_password: password }),
    onSuccess: async () => {
      setPassword("");
      await client.invalidateQueries();
      onClose();
    },
  });
  return (
    <Modal
      title="Restablecer contraseña"
      onClose={action.isPending ? () => {} : onClose}
    >
      <p>{user.email}</p>
      <Notice>Esta acción cierra todas las sesiones del usuario.</Notice>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          action.mutate();
        }}
      >
        <Field label="Nueva contraseña">
          <input
            type="password"
            required
            minLength={12}
            maxLength={128}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <ErrorNotice error={action.error} />
        <div className="actions">
          <Button busy={action.isPending} type="submit">
            Restablecer contraseña
          </Button>
        </div>
      </form>
    </Modal>
  );
}
export function AuditLog() {
  const [action, setAction] = useState("");
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [action, since, until]);
  const rows = useQuery({
    queryKey: ["audit", action, since, until, offset],
    queryFn: ({ signal }) =>
      api.get<Page<Audit>>(
        "/audit-logs" +
          query({
            action,
            since: since ? new Date(since).toISOString() : undefined,
            until: until ? new Date(until).toISOString() : undefined,
            offset,
            limit: 50,
          }),
        signal,
      ),
  });
  return (
    <>
      <PageTitle
        title="Auditoría"
        description="Consulta acciones registradas, responsables y contexto seguro."
      />
      <Panel>
        <div className="filter-grid">
          <Field label="Acción exacta">
            <input
              value={action}
              onChange={(e) => setAction(e.target.value)}
              placeholder="Ejemplo: auth.login"
              maxLength={100}
            />
          </Field>
          <Field label="Desde (hora local)">
            <input
              type="datetime-local"
              value={since}
              onChange={(e) => setSince(e.target.value)}
            />
          </Field>
          <Field label="Hasta (hora local)">
            <input
              type="datetime-local"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </Field>
        </div>
        <ErrorNotice error={rows.error} />
        {rows.isPending ? (
          <Loading />
        ) : rows.data?.items.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>Acción</th>
                  <th>Responsable</th>
                  <th>Entidad</th>
                  <th>Contexto</th>
                </tr>
              </thead>
              <tbody>
                {rows.data.items.map((r) => (
                  <tr key={r.id}>
                    <td>{formatDate(r.created_at)}</td>
                    <td>{r.action}</td>
                    <td className="mono">{r.actor_id || "Sistema"}</td>
                    <td className="mono">{r.entity_id || "—"}</td>
                    <td>
                      <details>
                        <summary>Ver detalle</summary>
                        <pre>{JSON.stringify(r.safe_context, null, 2)}</pre>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No hay eventos en esta selección" />
        )}
        <Pagination
          offset={offset}
          total={rows.data?.total || 0}
          limit={50}
          onChange={setOffset}
        />
      </Panel>
    </>
  );
}
export function Settings() {
  const { user, logout } = useSession();
  const [error, setError] = useState<unknown>(null);
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<{ current: string; next: string; confirm: string }>();
  const data = useQuery({
    queryKey: ["settings"],
    queryFn: ({ signal }) => api.get<SettingsType>("/settings", signal),
  });
  const health = useQuery({
    queryKey: ["health"],
    queryFn: async ({ signal }) => {
      const response = await fetch("/api/v1/health/ready", {
        credentials: "same-origin",
        cache: "no-store",
        signal,
      });
      if (!response.ok && response.status !== 503)
        throw new Error("No se pudo consultar el estado de los servicios.");
      return (await response.json()) as {
        status: string;
        checks: Record<string, boolean>;
      };
    },
    refetchInterval: 30000,
  });
  return (
    <>
      <PageTitle
        title="Configuración"
        description="Revisa los límites del entorno, su estado y la seguridad de tu cuenta."
      />
      <div className="dashboard-columns">
        <Panel title="Configuración del entorno">
          <ErrorNotice error={data.error} />
          {data.isPending ? (
            <Loading />
          ) : (
            data.data && (
              <dl className="definition-grid">
                <div>
                  <dt>Zona horaria</dt>
                  <dd>{data.data.timezone}</dd>
                </div>
                <div>
                  <dt>Tamaño máximo CSV</dt>
                  <dd>{number(data.data.csv_max_bytes / 1048576)} MB</dd>
                </div>
                <div>
                  <dt>Filas máximas por archivo</dt>
                  <dd>{number(data.data.csv_max_rows)}</dd>
                </div>
                <div>
                  <dt>Operaciones máximas</dt>
                  <dd>{number(data.data.csv_max_operations)}</dd>
                </div>
                <div>
                  <dt>Ejecución de matrículas</dt>
                  <dd>
                    {data.data.enrollment_writes_enabled
                      ? "Habilitada"
                      : "Deshabilitada por el administrador"}
                  </dd>
                </div>
              </dl>
            )
          )}
          <p className="muted">
            Los límites del entorno requieren intervención del administrador del
            despliegue. Los límites por instalación se gestionan en Conexiones
            Moodle.
          </p>
        </Panel>
        <Panel title="Estado de los servicios">
          <ErrorNotice error={health.error} />
          {health.data &&
            Object.entries(health.data.checks).map(([key, healthy]) => (
              <div className="service-row" key={key}>
                <span>
                  {(
                    {
                      postgresql: "Base de datos",
                      redis: "Cola de tareas",
                      token_encryption: "Configuración de cifrado",
                      validation_recovery: "Coordinador de validaciones",
                      enrollment_recovery: "Coordinador de matrículas",
                    } as Record<string, string>
                  )[key] || key}
                </span>
                <Badge state={healthy ? "valid" : "error"} />
              </div>
            ))}
          <p className="muted">
            Esta comprobación no certifica disponibilidad de Moodle ni actividad
            de cada ejecutor. Revisa también el progreso del proceso y la última
            comprobación del destino.
          </p>
        </Panel>
      </div>
      <Panel title="Seguridad de tu cuenta">
        <p>
          {user?.email} · {user?.roles.join(", ")}
        </p>
        <form
          className="password-form"
          onSubmit={handleSubmit(async (v) => {
            setError(null);
            if (v.next !== v.confirm) {
              setError(new Error("Las contraseñas no coinciden."));
              return;
            }
            try {
              await api.post("/auth/change-password", {
                current_password: v.current,
                new_password: v.next,
              });
              await logout().catch(() => {});
              window.dispatchEvent(new Event("session-expired"));
            } catch (e) {
              setError(e);
            }
          })}
        >
          <Field label="Contraseña actual">
            <input
              type="password"
              required
              maxLength={128}
              autoComplete="current-password"
              {...register("current")}
            />
          </Field>
          <Field label="Nueva contraseña">
            <input
              type="password"
              required
              minLength={12}
              maxLength={128}
              autoComplete="new-password"
              {...register("next")}
            />
          </Field>
          <Field label="Confirmar nueva contraseña">
            <input
              type="password"
              required
              minLength={12}
              maxLength={128}
              autoComplete="new-password"
              {...register("confirm")}
            />
          </Field>
          <ErrorNotice error={error} />
          <Button type="submit" busy={isSubmitting}>
            Cambiar contraseña y cerrar sesiones
          </Button>
        </form>
      </Panel>
    </>
  );
}
