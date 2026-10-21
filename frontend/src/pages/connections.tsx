import { useState } from "react";
import { useForm } from "react-hook-form";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Plug, Plus, ShieldCheck, Trash2 } from "lucide-react";
import { z } from "zod";
import { api, query } from "../api/client";
import type { Approval, Connection, Page, User } from "../types";
import {
  Badge,
  Button,
  Confirm,
  Empty,
  ErrorNotice,
  Field,
  formatDate,
  Loading,
  Modal,
  Notice,
  PageTitle,
  Pagination,
  Panel,
} from "../components/ui";
const defaults: Connection["limits"] = {
  timeout_seconds: 15,
  min_probe_interval_seconds: 30,
  requests_per_minute: 10,
  max_concurrency: 1,
  error_threshold: 3,
  circuit_cooldown_seconds: 300,
};
export function Connections() {
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<Connection | null | undefined>(
    undefined,
  );
  const [access, setAccess] = useState<string | null>(null);
  const [disable, setDisable] = useState<Connection | null>(null);
  const client = useQueryClient();
  const list = useQuery({
    queryKey: ["connections", offset],
    queryFn: ({ signal }) =>
      api.get<Page<Connection>>(
        "/moodle-connections" + query({ offset, limit: 25 }),
        signal,
      ),
  });
  const test = useMutation({
    mutationFn: (id: string) =>
      api.post<Connection>(`/moodle-connections/${id}/test`),
    onSuccess: () => client.invalidateQueries(),
  });
  const toggle = useMutation({
    mutationFn: () =>
      api.patch(`/moodle-connections/${disable!.id}`, {
        active: !disable!.active,
      }),
    onSuccess: async () => {
      setDisable(null);
      await client.invalidateQueries();
    },
  });
  return (
    <>
      <PageTitle
        title="Conexiones Moodle"
        description="Administra destinos, comprueba sus funciones y controla el acceso."
        action={
          <Button onClick={() => setEditing(null)}>
            <Plus size={16} />
            Nueva conexión
          </Button>
        }
      />
      <ErrorNotice error={test.error} />
      {test.data?.status === "error" && (
        <ErrorNotice
          error={
            new Error("La comprobación falló: " + test.data.last_error_code)
          }
        />
      )}
      <Panel>
        <ErrorNotice error={list.error} />
        {list.isPending ? (
          <Loading />
        ) : list.data?.items.length ? (
          <div className="connection-grid">
            {list.data.items.map((c) => (
              <article className="connection-card" key={c.id}>
                <div className="connection-card-head">
                  <span className="tile-icon">
                    <Plug size={22} />
                  </span>
                  <Badge state={c.status} />
                </div>
                <h2>{c.name}</h2>
                <p className="connection-url">{c.base_url}</p>
                <p>{c.description || "Sin descripción"}</p>
                <dl>
                  <div>
                    <dt>Última comprobación</dt>
                    <dd>{formatDate(c.last_verified_at)}</dd>
                  </div>
                  <div>
                    <dt>Límite de solicitudes</dt>
                    <dd>{c.limits.requests_per_minute} / min</dd>
                  </div>
                  <div>
                    <dt>Token</dt>
                    <dd>
                      {c.token_configured
                        ? "Configurado de forma segura"
                        : "Sin configurar"}
                    </dd>
                  </div>
                </dl>
                {c.last_error_code && (
                  <p className="error-text">{c.last_error_code}</p>
                )}
                <div className="connection-actions">
                  <Button
                    variant="secondary"
                    disabled={!c.active || test.isPending}
                    busy={test.isPending && test.variables === c.id}
                    onClick={() => test.mutate(c.id)}
                  >
                    <Check size={15} />
                    Probar conexión
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setEditing(c)}
                    aria-label={"Editar " + c.name}
                  >
                    <Pencil size={16} />
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => setAccess(c.id)}
                    aria-label={"Accesos y detalles de " + c.name}
                  >
                    <ShieldCheck size={17} />
                  </Button>
                  <Button
                    variant="ghost"
                    onClick={() => {
                      toggle.reset();
                      setDisable(c);
                    }}
                  >
                    {c.active ? "Desactivar" : "Activar"}
                  </Button>
                </div>
              </article>
            ))}
          </div>
        ) : (
          <Empty title="Conecta tu primera instalación Moodle">
            Necesitas una URL HTTPS pública y un token de servicios web
            autorizado.
          </Empty>
        )}
        <Pagination
          offset={offset}
          total={list.data?.total || 0}
          limit={25}
          onChange={setOffset}
        />
      </Panel>
      {editing !== undefined && (
        <ConnectionForm
          initial={editing}
          onClose={() => setEditing(undefined)}
        />
      )}{" "}
      {access && (
        <ConnectionAccess id={access} onClose={() => setAccess(null)} />
      )}{" "}
      {disable && (
        <Confirm
          title={disable.active ? "Desactivar conexión" : "Activar conexión"}
          onClose={() => setDisable(null)}
          busy={toggle.isPending}
          error={toggle.error}
          onConfirm={() => toggle.mutate()}
        >
          {disable.active
            ? "Se impedirán nuevos envíos y comprobaciones a este destino. Los trabajos e historial se conservarán."
            : "La conexión volverá a estar disponible. Deberás verificar de nuevo su configuración."}
        </Confirm>
      )}
    </>
  );
}
function ConnectionForm({
  initial,
  onClose,
}: {
  initial: Connection | null;
  onClose: () => void;
}) {
  type Values = {
    name: string;
    base_url: string;
    description: string;
    token: string;
  } & Connection["limits"];
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<Values>({
    defaultValues: {
      name: initial?.name || "",
      base_url: initial?.base_url || "",
      description: initial?.description || "",
      token: "",
      ...(initial?.limits || defaults),
    },
  });
  const [error, setError] = useState<unknown>(null);
  const client = useQueryClient();
  return (
    <Modal
      title={initial ? "Editar conexión" : "Nueva conexión Moodle"}
      onClose={isSubmitting ? () => {} : onClose}
    >
      <form
        onSubmit={handleSubmit(async (v) => {
          setError(null);
          if (
            !z.url().safeParse(v.base_url).success ||
            !v.base_url.startsWith("https://")
          ) {
            setError(new Error("Introduce una URL HTTPS válida."));
            return;
          }
          if ((!initial || v.base_url !== initial.base_url) && !v.token) {
            setError(
              new Error("La creación o cambio de URL requiere un token nuevo."),
            );
            return;
          }
          const { name, base_url, description, token, ...limits } = v;
          try {
            const body = {
              name,
              base_url,
              description,
              limits,
              ...(token ? { token } : {}),
            };
            if (initial)
              await api.patch("/moodle-connections/" + initial.id, body);
            else await api.post("/moodle-connections", body);
            await client.invalidateQueries();
            onClose();
          } catch (e) {
            setError(e);
          }
        })}
      >
        <Field label="Nombre de la conexión">
          <input required maxLength={200} {...register("name")} />
        </Field>
        <Field
          label="URL base de Moodle"
          hint="HTTPS y puerto 443. No se permiten direcciones internas ni redirecciones."
        >
          <input
            type="url"
            required
            placeholder="https://moodle.institucion.edu"
            {...register("base_url")}
          />
        </Field>
        <Field
          label={initial ? "Nuevo token (opcional)" : "Token de servicios web"}
          hint={
            initial
              ? "Vacío conserva el token actual. Cambiar la URL requiere proporcionar uno nuevo."
              : "Se cifra al guardarlo y nunca se devuelve en las consultas."
          }
        >
          <input
            type="password"
            autoComplete="new-password"
            required={!initial}
            maxLength={4096}
            {...register("token")}
          />
        </Field>
        <Field label="Descripción">
          <textarea rows={2} maxLength={2000} {...register("description")} />
        </Field>
        <details open>
          <summary>Límites de protección</summary>
          <div className="form-grid">
            {(
              [
                {
                  key: "requests_per_minute",
                  label: "Solicitudes por minuto",
                  min: 1,
                  max: 120,
                },
                {
                  key: "max_concurrency",
                  label: "Trabajos simultáneos máximos",
                  min: 1,
                  max: 4,
                },
                {
                  key: "timeout_seconds",
                  label: "Tiempo de respuesta (segundos)",
                  min: 3,
                  max: 60,
                },
                {
                  key: "min_probe_interval_seconds",
                  label: "Intervalo de comprobación (segundos)",
                  min: 5,
                  max: 3600,
                },
                {
                  key: "error_threshold",
                  label: "Umbral de errores de la instalación",
                  min: 1,
                  max: 20,
                },
                {
                  key: "circuit_cooldown_seconds",
                  label: "Enfriamiento (segundos)",
                  min: 30,
                  max: 3600,
                },
              ] as const
            ).map((f) => (
              <Field key={f.key} label={f.label}>
                <input
                  type="number"
                  required
                  min={f.min}
                  max={f.max}
                  {...register(f.key, { valueAsNumber: true })}
                />
              </Field>
            ))}
          </div>
          <p className="muted">
            Estos límites reducen la carga, pero no garantizan la capacidad de
            Moodle. Calíbralos primero en una instalación de ensayo.
          </p>
        </details>
        <ErrorNotice error={error} />
        <div className="actions">
          <Button
            type="button"
            variant="secondary"
            disabled={isSubmitting}
            onClick={onClose}
          >
            Volver
          </Button>
          <Button type="submit" busy={isSubmitting}>
            Guardar conexión
          </Button>
        </div>
      </form>
    </Modal>
  );
}
function ConnectionAccess({
  id,
  onClose,
}: {
  id: string;
  onClose: () => void;
}) {
  const [tab, setTab] = useState("details");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState("");
  const client = useQueryClient();
  const connection = useQuery({
    queryKey: ["connection", id],
    queryFn: ({ signal }) =>
      api.get<Connection>("/moodle-connections/" + id, signal),
  });
  const grants = useQuery({
    queryKey: ["grants", id],
    queryFn: ({ signal }) =>
      api.get<Page<{ user_id: string; email: string }>>(
        `/moodle-connections/${id}/grants`,
        signal,
      ),
    enabled: tab === "grants",
  });
  const users = useQuery({
    queryKey: ["grant-users", search],
    queryFn: ({ signal }) =>
      api.get<Page<User>>("/users" + query({ search, limit: 100 }), signal),
    enabled: tab === "grants",
  });
  const approvals = useQuery({
    queryKey: ["approvals", id],
    queryFn: ({ signal }) =>
      api.get<Page<Approval>>(
        `/moodle-connections/${id}/role-approvals?limit=100`,
        signal,
      ),
    enabled: tab === "approvals",
  });
  const checks = useQuery({
    queryKey: ["checks", id],
    queryFn: ({ signal }) =>
      api.get<
        Page<{
          id: string;
          status: string;
          error_code: string | null;
          created_at: string;
          latency_ms: number | null;
        }>
      >(`/moodle-connections/${id}/checks?limit=20`, signal),
    enabled: tab === "details",
  });
  const grant = useMutation({
    mutationFn: () =>
      api.post(`/moodle-connections/${id}/grants`, { user_id: selected }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["grants", id] }),
  });
  const revoke = useMutation({
    mutationFn: (userId: string) =>
      api.delete(`/moodle-connections/${id}/grants/${userId}`),
    onSuccess: () => client.invalidateQueries({ queryKey: ["grants", id] }),
  });
  const removeApproval = useMutation({
    mutationFn: (approval: string) => api.delete("/role-approvals/" + approval),
    onSuccess: () => client.invalidateQueries({ queryKey: ["approvals", id] }),
  });
  return (
    <Modal
      title={connection.data?.name || "Detalles de conexión"}
      onClose={onClose}
    >
      <div
        className="tabs"
        role="tablist"
        aria-label="Administración del destino"
      >
        {[
          { id: "details", name: "Comprobaciones" },
          { id: "grants", name: "Accesos" },
          { id: "approvals", name: "Roles verificados" },
        ].map((t) => (
          <button
            role="tab"
            aria-selected={tab === t.id}
            key={t.id}
            className={tab === t.id ? "active" : ""}
            onClick={() => setTab(t.id)}
          >
            {t.name}
          </button>
        ))}
      </div>
      <ErrorNotice error={connection.error} />
      {tab === "details" && (
        <>
          <p>{connection.data?.base_url}</p>
          <p className="muted">
            Versión de configuración: {connection.data?.configuration_version}
          </p>
          <details>
            <summary>Funciones anunciadas por Moodle</summary>
            {connection.data?.available_functions.length ? (
              <ul className="function-list">
                {connection.data.available_functions.map((f) => (
                  <li key={f}>{f}</li>
                ))}
              </ul>
            ) : (
              <p>No se han detectado funciones. Prueba la conexión.</p>
            )}
          </details>
          <ErrorNotice error={checks.error} />
          {checks.data?.items.length ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Fecha</th>
                    <th>Estado</th>
                    <th>Latencia</th>
                    <th>Detalle</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.data.items.map((r) => (
                    <tr key={r.id}>
                      <td>{formatDate(r.created_at)}</td>
                      <td>
                        <Badge state={r.status} />
                      </td>
                      <td>
                        {r.latency_ms === null ? "—" : r.latency_ms + " ms"}
                      </td>
                      <td>{r.error_code || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <Empty title="Todavía no hay comprobaciones" />
          )}
        </>
      )}
      {tab === "grants" && (
        <>
          <Notice>
            Los operadores requieren una concesión para usar el destino.
            Supervisores y usuarios de consulta sólo pueden revisar procesos
            según sus roles.
          </Notice>
          <Field label="Buscar usuario por correo">
            <input
              type="search"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setSelected("");
              }}
            />
          </Field>
          <div className="inline-form">
            <Field label="Usuario a autorizar">
              <select
                value={selected}
                onChange={(e) => setSelected(e.target.value)}
              >
                <option value="">Seleccionar usuario</option>
                {users.data?.items
                  .filter((u) => u.active)
                  .map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.email}
                    </option>
                  ))}
              </select>
            </Field>
            <Button
              disabled={!selected}
              busy={grant.isPending}
              onClick={() => grant.mutate()}
            >
              Conceder acceso
            </Button>
          </div>
          <ErrorNotice
            error={grants.error || users.error || grant.error || revoke.error}
          />
          {grants.data?.items.map((g) => (
            <div className="access-row" key={g.user_id}>
              <span>{g.email}</span>
              <Button
                variant="danger"
                busy={revoke.isPending && revoke.variables === g.user_id}
                onClick={() => revoke.mutate(g.user_id)}
              >
                Revocar
              </Button>
            </div>
          ))}
        </>
      )}
      {tab === "approvals" && (
        <>
          <ApprovalForm id={id} />
          <ErrorNotice error={approvals.error || removeApproval.error} />
          <h3>Evidencias registradas</h3>
          {approvals.data?.items.length ? (
            approvals.data.items.map((a) => (
              <div className="approval-card" key={a.id}>
                <div>
                  <strong>
                    Curso {a.course_id} · Rol {a.role_id}
                  </strong>
                  <Badge state={a.active ? "valid" : "disabled"} />
                </div>
                <p>{a.reference}</p>
                <small>
                  Caduca: {formatDate(a.expires_at)} · Configuración{" "}
                  {a.configuration_version}
                </small>
                <p className="muted">
                  Visibilidad completa:{" "}
                  {a.full_enrollment_visibility ? "Sí" : "No"} · Gestión de
                  grupos: {a.groups_authorized ? "Verificada" : "No verificada"}
                </p>
                {a.active && (
                  <Button
                    variant="danger"
                    busy={
                      removeApproval.isPending &&
                      removeApproval.variables === a.id
                    }
                    onClick={() => removeApproval.mutate(a.id)}
                  >
                    <Trash2 size={14} />
                    Revocar evidencia
                  </Button>
                )}
              </div>
            ))
          ) : (
            <Empty title="Sin evidencias registradas" />
          )}
        </>
      )}
    </Modal>
  );
}
function ApprovalForm({ id }: { id: string }) {
  type Values = {
    course_id: number;
    role_id: number;
    expires: string;
    reference: string;
    full_enrollment_visibility: boolean;
    groups_authorized: boolean;
  };
  const {
    register,
    handleSubmit,
    reset,
    formState: { isSubmitting },
  } = useForm<Values>();
  const [error, setError] = useState<unknown>(null);
  const client = useQueryClient();
  return (
    <form
      className="approval-form"
      onSubmit={handleSubmit(async (v) => {
        setError(null);
        if (!v.full_enrollment_visibility) {
          setError(
            new Error(
              "Debes comprobar y confirmar la visibilidad completa en Moodle.",
            ),
          );
          return;
        }
        try {
          await api.post(`/moodle-connections/${id}/role-approvals`, {
            course_id: v.course_id,
            role_id: v.role_id,
            reference: v.reference,
            expires_at: new Date(v.expires).toISOString(),
            full_enrollment_visibility: v.full_enrollment_visibility,
            groups_authorized: !!v.groups_authorized,
          });
          reset();
          await client.invalidateQueries({ queryKey: ["approvals", id] });
        } catch (e) {
          setError(e);
        }
      })}
    >
      <Notice>
        Registra sólo comprobaciones realizadas en Moodle: rol asignable por el
        usuario técnico y visibilidad de todos los participantes, incluidos
        grupos separados. Esta evidencia no crea permisos en Moodle.
      </Notice>
      <div className="form-grid">
        <Field label="ID interno del curso">
          <input
            type="number"
            required
            min={1}
            max={2147483647}
            {...register("course_id", { valueAsNumber: true })}
          />
        </Field>
        <Field label="ID del rol verificado">
          <input
            type="number"
            required
            min={1}
            max={2147483647}
            {...register("role_id", { valueAsNumber: true })}
          />
        </Field>
      </div>
      <Field
        label="Caducidad (hora local del navegador)"
        hint="Máximo siete días desde ahora."
      >
        <input type="datetime-local" required {...register("expires")} />
      </Field>
      <Field label="Referencia de la comprobación">
        <textarea
          required
          minLength={20}
          maxLength={1000}
          rows={2}
          {...register("reference")}
        />
      </Field>
      <label className="check-field">
        <input
          type="checkbox"
          required
          {...register("full_enrollment_visibility")}
        />
        He comprobado que el rol es asignable y que el usuario técnico ve todos
        los participantes del curso.
      </label>
      <label className="check-field">
        <input type="checkbox" {...register("groups_authorized")} />
        También he comprobado los permisos para gestionar grupos.
      </label>
      <ErrorNotice error={error} />
      <div className="actions">
        <Button type="submit" busy={isSubmitting}>
          Registrar evidencia
        </Button>
      </div>
    </form>
  );
}
