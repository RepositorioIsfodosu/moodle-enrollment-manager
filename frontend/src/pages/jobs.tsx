import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Copy,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Square,
} from "lucide-react";
import { api, query } from "../api/client";
import type { Attempt, Event, Job, Operation, Page } from "../types";
import { useScope } from "../components/layout";
import { useSession } from "../components/session";
import {
  Badge,
  Button,
  Confirm,
  Empty,
  ErrorNotice,
  Field,
  formatDate,
  labels,
  Loading,
  Notice,
  number,
  PageTitle,
  Pagination,
  Panel,
  Progress,
} from "../components/ui";
import { JobCreate } from "../components/job-create";
import { OperationTable } from "../components/operation-table";
const terminal = ["completed", "completed_with_errors", "failed", "cancelled"];
export function Jobs({ history = false }: { history?: boolean }) {
  const { connection, destinations } = useScope();
  const { can } = useSession();
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState("");
  useEffect(() => setOffset(0), [connection, state, history]);
  const data = useQuery({
    queryKey: ["jobs", connection, state, offset, history],
    queryFn: ({ signal }) =>
      api.get<Page<Job>>(
        "/enrollment-jobs" +
          query({
            connection_id: connection,
            state,
            terminal: history ? true : undefined,
            offset,
            limit: 25,
          }),
        signal,
      ),
    refetchInterval: 5000,
  });
  return (
    <>
      <PageTitle
        title={history ? "Historial de procesos" : "Procesos de matriculación"}
        description={
          history
            ? "Revisa procesos terminados y su trazabilidad."
            : "Supervisa el avance y controla las operaciones de cada proceso."
        }
        action={
          can("imports:write") && (
            <Link to="/new" className="btn btn-primary">
              <Plus size={16} />
              Nueva matriculación
            </Link>
          )
        }
      />
      <Panel>
        <div className="toolbar">
          <Field label="Estado">
            <select value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">Todos los estados</option>
              {(history
                ? terminal
                : [
                    "draft",
                    "ready",
                    "queued",
                    "running",
                    "pausing",
                    "paused",
                    "cancelling",
                    ...terminal,
                  ]
              ).map((s) => (
                <option key={s} value={s}>
                  {labels[s]}
                </option>
              ))}
            </select>
          </Field>
          <span className="muted">Actualización cada 5 segundos</span>
        </div>
        <ErrorNotice error={data.error} />
        {data.isPending ? (
          <Loading />
        ) : data.data?.items.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Proceso</th>
                  <th>Instalación</th>
                  <th>Estado</th>
                  <th>Operaciones</th>
                  <th>Progreso</th>
                  <th>Creado</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {data.data.items.map((j) => (
                  <tr key={j.id}>
                    <td>
                      <Link className="row-link" to={"/jobs/" + j.id}>
                        {j.name}
                      </Link>
                    </td>
                    <td>
                      {destinations.find((d) => d.id === j.connection_id)
                        ?.name || "Destino histórico"}
                    </td>
                    <td>
                      <Badge state={j.state} />
                    </td>
                    <td>{number(j.total)}</td>
                    <td>
                      <Progress value={j.progress_percent} />
                    </td>
                    <td>{formatDate(j.created_at)}</td>
                    <td>
                      <Link to={"/jobs/" + j.id} aria-label={"Ver " + j.name}>
                        <ArrowRight size={17} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No hay procesos en esta selección" />
        )}
        <Pagination
          offset={offset}
          total={data.data?.total || 0}
          limit={25}
          onChange={setOffset}
        />
      </Panel>
    </>
  );
}
export function JobDetail() {
  const { id = "" } = useParams();
  const { can } = useSession();
  const { destinations } = useScope();
  const [tab, setTab] = useState<"records" | "attempts" | "events">("records");
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState("");
  const [selected, setSelected] = useState(new Set<string>());
  const [action, setAction] = useState<string | null>(null);
  const [duplicate, setDuplicate] = useState(false);
  const client = useQueryClient();
  const navigate = useNavigate();
  useEffect(() => {
    setOffset(0);
    setSelected(new Set());
  }, [id, tab, state]);
  const job = useQuery({
    queryKey: ["job", id],
    queryFn: ({ signal }) => api.get<Job>("/enrollment-jobs/" + id, signal),
    refetchInterval: 5000,
  });
  const rows = useQuery({
    queryKey: ["job-rows", id, tab, offset, state],
    queryFn: ({ signal }) =>
      api.get<Page<Operation | Attempt | Event>>(
        `/enrollment-jobs/${id}/${tab}` +
          query({
            offset,
            limit: 50,
            state: tab === "records" ? state : undefined,
          }),
        signal,
      ),
    refetchInterval: 5000,
  });
  const change = useMutation({
    mutationFn: async () =>
      action === "retry"
        ? api.post<Job>(`/enrollment-jobs/${id}/retry`, {
            record_ids: [...selected],
          })
        : api.post<Job>(`/enrollment-jobs/${id}/${action}`),
    onSuccess: async (result) => {
      if (action === "retry") navigate("/jobs/" + result.id);
      setAction(null);
      setSelected(new Set());
      await client.invalidateQueries();
    },
  });
  if (job.isPending) return <Loading />;
  if (!job.data) return <ErrorNotice error={job.error} />;
  const j = job.data;
  const active = !terminal.includes(j.state);
  const end = j.finished_at ? new Date(j.finished_at).getTime() : Date.now();
  const elapsed = j.started_at
    ? Math.max(0, (end - new Date(j.started_at).getTime()) / 1000)
    : null;
  const processed = Object.entries(j.counts)
    .filter(([s]) => !["pending", "reserved"].includes(s))
    .reduce((n, [, v]) => n + v, 0);
  const rate = elapsed && processed ? processed / elapsed : null;
  const eta =
    rate && processed >= 3 && j.state === "running" && j.total > processed
      ? (j.total - processed) / rate
      : null;
  const choose = (a: string) => {
    change.reset();
    setAction(a);
  };
  return (
    <>
      <Link className="back-link" to="/jobs">
        <ArrowLeft size={15} />
        Todos los procesos
      </Link>
      <PageTitle
        eyebrow="DETALLE DEL PROCESO"
        title={j.name}
        description={
          "Destino: " +
          (destinations.find((d) => d.id === j.connection_id)?.name ||
            "instalación histórica")
        }
        action={
          <div className="actions">
            {can("jobs:write") && (
              <>
                <Button variant="secondary" onClick={() => setDuplicate(true)}>
                  <Copy size={15} />
                  Duplicar configuración
                </Button>
                {["draft", "ready", "paused"].includes(j.state) && (
                  <Button
                    disabled={!j.configuration.execution_available}
                    onClick={() =>
                      choose(j.state === "paused" ? "resume" : "start")
                    }
                  >
                    <Play size={15} />
                    {j.state === "paused" ? "Reanudar" : "Iniciar proceso"}
                  </Button>
                )}
                {["queued", "running"].includes(j.state) && (
                  <Button variant="secondary" onClick={() => choose("pause")}>
                    <Pause size={15} />
                    Pausar
                  </Button>
                )}
                {active && j.state !== "cancelling" && (
                  <Button variant="danger" onClick={() => choose("cancel")}>
                    <Square size={14} />
                    Cancelar
                  </Button>
                )}
              </>
            )}
          </div>
        }
      />
      <ErrorNotice error={job.error} />
      {!j.configuration.execution_available && (
        <Notice>
          El administrador no ha habilitado la ejecución de matrículas. Puedes
          revisar el borrador y sus registros.
        </Notice>
      )}
      <div className="process-banner">
        <div>
          <Badge state={j.state} />
          <span>
            {number(processed)} de {number(j.total)} operaciones atendidas
          </span>
        </div>
        <Progress value={j.progress_percent} />
        <small>
          El porcentaje incluye resultados fallidos e inciertos; consulta el
          desglose.
        </small>
      </div>
      <div className="stats-grid six">
        {[
          "confirmed",
          "existing",
          "pending",
          "failed",
          "uncertain",
          "skipped",
        ].map((s) => (
          <div className="stat-card compact" key={s}>
            <span>{labels[s]}</span>
            <strong>
              {number(
                (j.counts[s] || 0) +
                  (s === "pending" ? j.counts.reserved || 0 : 0),
              )}
            </strong>
          </div>
        ))}
      </div>
      <div className="runtime-strip">
        <span>
          Tiempo transcurrido
          <strong>
            {elapsed === null
              ? "—"
              : `${Math.floor(elapsed / 60)} min ${Math.floor(elapsed % 60)} s`}
          </strong>
        </span>
        <span title="Promedio acumulado, incluidas pausas">
          Ritmo promedio
          <strong>{rate ? `${(rate * 60).toFixed(1)} op/min` : "—"}</strong>
        </span>
        <span title="Estimación basada en el promedio acumulado; puede variar por pausas y reintentos">
          Restante estimado
          <strong>
            {eta ? `${Math.ceil(eta / 60)} min` : "Datos insuficientes"}
          </strong>
        </span>
        <span>
          Actividad del ejecutor
          <strong>{formatDate(j.runtime.worker_seen_at)}</strong>
        </span>
        <span>
          Última respuesta Moodle
          <strong>
            {j.runtime.last_latency_ms !== undefined
              ? j.runtime.last_latency_ms + " ms"
              : "Sin medición"}
          </strong>
        </span>
      </div>
      <Panel>
        <div
          className="tabs"
          role="tablist"
          aria-label="Información del proceso"
        >
          {(["records", "attempts", "events"] as const).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              className={tab === t ? "active" : ""}
              onClick={() => setTab(t)}
            >
              {t === "records"
                ? "Registros"
                : t === "attempts"
                  ? "Intentos"
                  : "Eventos"}
            </button>
          ))}
        </div>
        {tab === "records" && (
          <div className="toolbar">
            <Field label="Estado del registro">
              <select value={state} onChange={(e) => setState(e.target.value)}>
                <option value="">Todos</option>
                {[
                  "pending",
                  "reserved",
                  "confirmed",
                  "existing",
                  "failed",
                  "uncertain",
                  "skipped",
                ].map((s) => (
                  <option key={s} value={s}>
                    {labels[s]}
                  </option>
                ))}
              </select>
            </Field>
            {can("jobs:write") && terminal.includes(j.state) && (
              <Button
                variant="secondary"
                disabled={!selected.size}
                onClick={() => choose("retry")}
              >
                <RefreshCw size={15} />
                Reintentar selección ({selected.size})
              </Button>
            )}
          </div>
        )}
        <ErrorNotice error={rows.error} />
        {rows.isPending ? (
          <Loading />
        ) : tab === "records" ? (
          <OperationTable
            rows={(rows.data?.items || []) as Operation[]}
            selected={selected}
            onToggle={
              can("jobs:write") && terminal.includes(j.state)
                ? (key) =>
                    setSelected((previous) => {
                      const next = new Set(previous);
                      if (next.has(key)) next.delete(key);
                      else next.add(key);
                      return next;
                    })
                : undefined
            }
          />
        ) : rows.data?.items.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Fecha</th>
                  <th>{tab === "attempts" ? "Resultado" : "Acción"}</th>
                  <th>Detalle</th>
                </tr>
              </thead>
              <tbody>
                {rows.data.items.map((raw) => {
                  const r = raw as Attempt & Event;
                  return (
                    <tr key={r.id}>
                      <td>{formatDate(r.created_at)}</td>
                      <td>
                        {tab === "attempts" ? (
                          <Badge state={r.outcome} />
                        ) : (
                          r.action
                        )}
                      </td>
                      <td>
                        {r.error_code && <span>{r.error_code}</span>}
                        <details>
                          <summary>Ver contexto</summary>
                          <pre>{JSON.stringify(r.context, null, 2)}</pre>
                        </details>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty />
        )}
        <Pagination
          offset={offset}
          total={rows.data?.total || 0}
          limit={50}
          onChange={setOffset}
        />
        <div className="data-freshness">
          Última consulta al servidor:{" "}
          {new Date(job.dataUpdatedAt).toLocaleTimeString("es-DO")}
        </div>
      </Panel>
      <Panel title="Configuración utilizada">
        <dl className="definition-grid">
          <div>
            <dt>Creado</dt>
            <dd>{formatDate(j.created_at)}</dd>
          </div>
          <div>
            <dt>Inicio</dt>
            <dd>{formatDate(j.started_at)}</dd>
          </div>
          <div>
            <dt>Finalización</dt>
            <dd>{formatDate(j.finished_at)}</dd>
          </div>
          <div>
            <dt>Lote</dt>
            <dd>{j.configuration.batch_size} operaciones</dd>
          </div>
          <div>
            <dt>Pausa mínima</dt>
            <dd>{j.configuration.pause_seconds} s</dd>
          </div>
          <div>
            <dt>Pausa efectiva</dt>
            <dd>
              {j.runtime.effective_pause_seconds ||
                j.configuration.pause_seconds}{" "}
              s
            </dd>
          </div>
          <div>
            <dt>Reintentos transitorios</dt>
            <dd>{j.configuration.max_retries}</dd>
          </div>
          <div>
            <dt>Horas UTC</dt>
            <dd>{j.configuration.allowed_hours_utc?.join(", ")}</dd>
          </div>
        </dl>
      </Panel>
      {action && (
        <Confirm
          title={
            action === "start"
              ? "Iniciar matriculación"
              : action === "resume"
                ? "Reanudar proceso"
                : action === "pause"
                  ? "Pausar proceso"
                  : action === "cancel"
                    ? "Cancelar proceso"
                    : "Reintentar registros"
          }
          onClose={() => setAction(null)}
          busy={change.isPending}
          error={change.error}
          onConfirm={() => change.mutate()}
        >
          {action === "start" || action === "resume"
            ? `Se enviarán operaciones a Moodle para «${j.name}» según sus límites y permisos.`
            : action === "cancel"
              ? "Las operaciones ya enviadas pueden terminar. La cancelación conserva resultados e historial."
              : action === "pause"
                ? "Se detendrán nuevos envíos; una operación ya enviada puede terminar."
                : "Se creará un borrador con la selección. Los resultados inciertos sólo se reconciliarán; no se reenviarán automáticamente."}
        </Confirm>
      )}
      {duplicate && (
        <JobCreate
          validationId={j.configuration.validation_id}
          config={j.configuration}
          name={j.name.slice(0, 180) + " — copia"}
          onClose={() => setDuplicate(false)}
        />
      )}
    </>
  );
}
export function Errors() {
  const { connection } = useScope();
  const [state, setState] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => setOffset(0), [state, connection]);
  const rows = useQuery({
    queryKey: ["errors", connection, state, offset],
    queryFn: ({ signal }) =>
      api.get<Page<Operation>>(
        "/enrollment-records" +
          query({ connection_id: connection, state, offset, limit: 50 }),
        signal,
      ),
    refetchInterval: 5000,
  });
  return (
    <>
      <PageTitle
        title="Errores e incertidumbres"
        description="Investiga los registros que requieren atención antes de solicitar un reintento."
      />
      <Panel>
        <div className="toolbar">
          <Field label="Tipo de incidencia">
            <select value={state} onChange={(e) => setState(e.target.value)}>
              <option value="">Todas</option>
              <option value="failed">Fallidas</option>
              <option value="uncertain">Inciertas</option>
            </select>
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
                  <th>Proceso</th>
                  <th>Fila</th>
                  <th>Usuario</th>
                  <th>Curso</th>
                  <th>Estado</th>
                  <th>Motivo</th>
                </tr>
              </thead>
              <tbody>
                {rows.data.items.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <Link className="row-link" to={"/jobs/" + r.job_id}>
                        {r.job_name}
                      </Link>
                    </td>
                    <td>{r.source_row}</td>
                    <td>{r.user_identifier}</td>
                    <td>{r.course_identifier}</td>
                    <td>
                      <Badge state={r.state || "failed"} />
                    </td>
                    <td>{r.error_code || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="No hay incidencias en esta selección" />
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
