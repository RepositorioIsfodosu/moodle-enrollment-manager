import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  ArrowUpRight,
  CheckCheck,
  CircleDashed,
  Clock3,
  FileSpreadsheet,
  Layers,
  Plus,
  ShieldAlert,
} from "lucide-react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, query } from "../api/client";
import type { Job, Page } from "../types";
import { useScope } from "../components/layout";
import { useSession } from "../components/session";
import {
  Badge,
  Empty,
  ErrorNotice,
  Loading,
  Notice,
  number,
  PageTitle,
  Panel,
  Progress,
  labels,
  formatDate,
} from "../components/ui";
interface Summary {
  imported_rows: number | null;
  job_counts: Record<string, number>;
  record_counts: Record<string, number>;
  total_operations: number;
}
export function Dashboard({ reports = false }: { reports?: boolean }) {
  const { connection } = useScope();
  const { can } = useSession();
  const summary = useQuery({
    queryKey: ["dashboard", connection],
    queryFn: ({ signal }) =>
      api.get<Summary>(
        "/dashboard" + query({ connection_id: connection }),
        signal,
      ),
    refetchInterval: 5000,
  });
  const jobs = useQuery({
    queryKey: ["recent-jobs", connection],
    queryFn: ({ signal }) =>
      api.get<Page<Job>>(
        "/enrollment-jobs" + query({ connection_id: connection, limit: 6 }),
        signal,
      ),
    refetchInterval: 5000,
  });
  const c = summary.data?.record_counts || {};
  const j = summary.data?.job_counts || {};
  const stats = [
    {
      label: "Registros importados",
      value: summary.data?.imported_rows,
      icon: FileSpreadsheet,
      note: connection
        ? "Filas de archivos vinculados a los trabajos"
        : "Filas CSV visibles para tu usuario",
    },
    {
      label: "Matrículas confirmadas",
      value: summary.data ? c.confirmed || 0 : null,
      icon: CheckCheck,
      note: "Estado solicitado observado en Moodle",
    },
    {
      label: "Matrículas pendientes",
      value: summary.data ? (c.pending || 0) + (c.reserved || 0) : null,
      icon: Clock3,
      note: "En espera o en procesamiento",
    },
    {
      label: "Requieren atención",
      value: summary.data ? (c.failed || 0) + (c.uncertain || 0) : null,
      icon: ShieldAlert,
      note: "Fallidas o con resultado incierto",
    },
  ];
  return (
    <>
      <PageTitle
        title={reports ? "Resumen operativo" : "Vista general"}
        description={
          reports
            ? "Consulta resultados persistidos de los procesos a los que tienes acceso."
            : "Una visión clara de tus importaciones y procesos de matriculación."
        }
        action={
          can("imports:write") && (
            <Link className="btn btn-primary" to="/new">
              <Plus size={17} />
              Nueva matriculación
            </Link>
          )
        }
      />
      {reports && (
        <Notice>
          Las exportaciones CSV, Excel y PDF se incorporarán en la Fase 7. Este
          resumen utiliza los resultados actuales del sistema.
        </Notice>
      )}
      <ErrorNotice error={summary.error} />
      {summary.isPending ? (
        <Loading />
      ) : (
        <div className="stats-grid">
          {stats.map((s) => (
            <section className="stat-card" key={s.label}>
              <div>
                <span>{s.label}</span>
                <s.icon size={18} />
              </div>
              <strong>{number(s.value)}</strong>
              <small>{s.note}</small>
            </section>
          ))}
        </div>
      )}
      <div className="dashboard-columns">
        <Panel
          title="Resultados de matriculación"
          action={
            <span className="muted">
              {number(summary.data?.total_operations)} operaciones
            </span>
          }
        >
          {summary.data?.total_operations ? (
            <>
              <div
                className="chart"
                role="img"
                aria-label={Object.entries(c)
                  .map(([s, n]) => `${labels[s] || s}: ${n}`)
                  .join(", ")}
              >
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart
                    data={[
                      "confirmed",
                      "existing",
                      "pending",
                      "failed",
                      "uncertain",
                      "skipped",
                    ].map((state) => ({
                      name: labels[state],
                      total: c[state] || 0,
                    }))}
                    margin={{ left: 0, right: 10, top: 15, bottom: 0 }}
                  >
                    <CartesianGrid vertical={false} stroke="#edf0f4" />
                    <XAxis
                      dataKey="name"
                      tick={{ fontSize: 10 }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      allowDecimals={false}
                      axisLine={false}
                      tickLine={false}
                      tick={{ fontSize: 11 }}
                      width={35}
                    />
                    <Tooltip cursor={{ fill: "#f7f8fc" }} />
                    <Bar
                      isAnimationActive={false}
                      name="Operaciones"
                      dataKey="total"
                      fill="#6475d8"
                      radius={[5, 5, 0, 0]}
                      maxBarSize={40}
                    />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <div className="summary-strip">
                <span>
                  Existentes <strong>{number(c.existing || 0)}</strong>
                </span>
                <span>
                  Inciertas <strong>{number(c.uncertain || 0)}</strong>
                </span>
                <span>
                  Omitidas <strong>{number(c.skipped || 0)}</strong>
                </span>
              </div>
            </>
          ) : (
            <Empty title="Tu actividad aparecerá aquí">
              Cuando ejecutes un trabajo podrás consultar sus resultados.
            </Empty>
          )}
        </Panel>
        <Panel title="Estado de los procesos">
          <div className="job-totals">
            {[
              {
                name: "Activos",
                icon: Layers,
                total:
                  (j.running || 0) +
                  (j.queued || 0) +
                  (j.pausing || 0) +
                  (j.cancelling || 0),
              },
              { name: "Pausados", icon: CircleDashed, total: j.paused || 0 },
              {
                name: "Completados",
                icon: CheckCheck,
                total: (j.completed || 0) + (j.completed_with_errors || 0),
              },
            ].map((s) => (
              <div key={s.name}>
                <span className="tile-icon">
                  <s.icon size={20} />
                </span>
                <span>{s.name}</span>
                <strong>{summary.data ? number(s.total) : "—"}</strong>
              </div>
            ))}
          </div>
          <Link className="text-link" to="/jobs">
            Ver todos los procesos <ArrowRight size={15} />
          </Link>
        </Panel>
      </div>
      <Panel
        title="Procesos recientes"
        action={
          <Link className="text-link" to="/jobs">
            Ver procesos <ArrowUpRight size={15} />
          </Link>
        }
      >
        <ErrorNotice error={jobs.error} />
        {jobs.isPending ? (
          <Loading />
        ) : jobs.data?.items.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Proceso</th>
                  <th>Creado</th>
                  <th>Operaciones</th>
                  <th>Progreso</th>
                  <th>Estado</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {jobs.data.items.map((job) => (
                  <tr key={job.id}>
                    <td>
                      <Link className="row-link" to={"/jobs/" + job.id}>
                        {job.name}
                      </Link>
                    </td>
                    <td>{formatDate(job.created_at)}</td>
                    <td>{number(job.total)}</td>
                    <td>
                      <Progress value={job.progress_percent} />
                    </td>
                    <td>
                      <Badge state={job.state} />
                    </td>
                    <td>
                      <Link
                        to={"/jobs/" + job.id}
                        aria-label={"Ver " + job.name}
                      >
                        <ArrowRight size={17} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="Aún no hay procesos">
            Crea una matriculación para empezar.
          </Empty>
        )}
      </Panel>
    </>
  );
}
