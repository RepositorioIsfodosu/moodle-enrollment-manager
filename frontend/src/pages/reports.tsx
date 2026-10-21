import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Download, Filter } from "lucide-react";
import { api, download, query } from "../api/client";
import { useScope } from "../components/layout";
import { useSession } from "../components/session";
import {
  Button,
  Empty,
  ErrorNotice,
  Field,
  Loading,
  Notice,
  PageTitle,
  Panel,
  Pagination,
  number,
  formatDate,
  labels,
} from "../components/ui";
interface Report {
  title: string;
  generated_at: string;
  columns: string[];
  items: Record<string, unknown>[];
  total: number;
  offset: number;
  limit: number;
  export_limit: number;
  summary: {
    total_operations: number;
    counts: Record<string, number>;
    percentages: Record<string, number>;
  };
}
const kinds: Record<string, string> = {
  general: "General",
  successful: "Matrículas confirmadas",
  errors: "Errores e incertidumbre",
  pending: "Pendientes",
  course: "Por curso",
  campus: "Por recinto",
  audit: "Auditoría",
};
export function Reports() {
  const { connection } = useScope();
  const { can } = useSession();
  const [draft, setDraft] = useState<Record<string, string>>({
    kind: "general",
  });
  const [applied, setApplied] = useState<Record<string, string>>({
    kind: "general",
  });
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<unknown>(null);
  const params = {
    ...applied,
    connection_id: applied.kind === "audit" ? "" : connection,
  };
  const result = useQuery({
    queryKey: ["reports", params, offset],
    queryFn: ({ signal }) =>
      api.get<Report>(
        "/reports" + query({ ...params, offset, limit: 25 }),
        signal,
      ),
  });
  const audit = draft.kind === "audit";
  async function exportFile(format: string) {
    setBusy(format);
    setError(null);
    try {
      await download(
        "/reports/export" + query({ ...params, format }),
        `reporte-${applied.kind}.${format}`,
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy("");
    }
  }
  function field(key: string, label: string, type = "text") {
    return (
      <Field label={label}>
        <input
          type={type}
          value={draft[key] || ""}
          onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
        />
      </Field>
    );
  }
  return (
    <>
      <PageTitle
        title="Reportes"
        description="Consulta resultados persistidos y exporta informes con los mismos filtros y permisos."
      />
      <Panel title="Filtros del informe">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const next = { ...draft };
            for (const key of ["since", "until"])
              if (next[key]) next[key] = new Date(next[key]).toISOString();
            setApplied(next);
            setOffset(0);
          }}
        >
          <div className="form-grid">
            <Field label="Tipo de reporte">
              <select
                value={draft.kind}
                onChange={(e) => {
                  setDraft({ kind: e.target.value });
                }}
              >
                {Object.entries(kinds)
                  .filter(([k]) => k !== "audit" || can("audit:read"))
                  .map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
              </select>
            </Field>
            {field(
              "since",
              "Desde (hora local del navegador)",
              "datetime-local",
            )}
            {field(
              "until",
              "Hasta (hora local del navegador)",
              "datetime-local",
            )}
            {audit ? (
              <>
                {field("actor_id", "ID del responsable")}
                {field("action", "Acción de auditoría")}
              </>
            ) : (
              <>
                {field("job_id", "ID del proceso")}
                {field("file_id", "ID del archivo")}
                {field("user", "Identificador de usuario")}
                {field("course", "Identificador de curso")}
                {field("campus", "Recinto (metadato campus)")}
                {field(
                  "academic_period",
                  "Período académico (metadato academic_period)",
                )}
                {field("error_code", "Código de error")}
                <Field label="Estado">
                  <select
                    value={draft.state || ""}
                    onChange={(e) =>
                      setDraft({ ...draft, state: e.target.value })
                    }
                  >
                    <option value="">Todos</option>
                    {[
                      "pending",
                      "valid",
                      "invalid",
                      "duplicate",
                      "reserved",
                      "confirmed",
                      "existing",
                      "failed",
                      "uncertain",
                      "skipped",
                    ].map((s) => (
                      <option key={s} value={s}>
                        {labels[s] || s}
                      </option>
                    ))}
                  </select>
                </Field>
              </>
            )}
          </div>
          <Button type="submit">
            <Filter size={16} /> Aplicar filtros
          </Button>
        </form>
      </Panel>
      <Notice>
        Los filtros se aplican al pulsar Aplicar filtros; la instalación se toma
        del selector superior. Las fechas corresponden a la creación de
        registros o eventos, con límites inclusivos. Los identificadores y
        metadatos requieren coincidencia exacta.
      </Notice>
      <ErrorNotice error={result.error || error} />
      {result.isPending ? (
        <Loading />
      ) : (
        result.data && (
          <>
            <div className="stats-grid">
              <Panel title="Operaciones / eventos">
                <strong>{number(result.data.summary.total_operations)}</strong>
              </Panel>
              {Object.entries(result.data.summary.counts).map(
                ([state, count]) => (
                  <Panel key={state} title={labels[state] || state}>
                    <strong>{number(count)}</strong>
                    <p>{result.data!.summary.percentages[state]} %</p>
                  </Panel>
                ),
              )}
            </div>
            <Panel
              title={result.data.title}
              action={
                <div className="button-row">
                  {["csv", "xlsx", "pdf"].map((format) => (
                    <Button
                      key={format}
                      variant="secondary"
                      busy={busy === format}
                      disabled={
                        !!busy || result.data!.total > result.data!.export_limit
                      }
                      onClick={() => void exportFile(format)}
                    >
                      <Download size={16} />
                      {format.toUpperCase()}
                    </Button>
                  ))}
                </div>
              }
            >
              <p className="muted">
                Consultado: {formatDate(result.data.generated_at)} ·{" "}
                {number(result.data.total)} filas · Máximo por exportación:{" "}
                {number(result.data.export_limit)}.
              </p>
              {result.data.total > result.data.export_limit && (
                <Notice>
                  Reduce el período o aplica filtros para exportar. Nunca se
                  truncan resultados.
                </Notice>
              )}
              {result.data.items.length ? (
                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        {result.data.columns.map((c) => (
                          <th key={c}>{c.replaceAll("_", " ")}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.data.items.map((row, i) => (
                        <tr key={String(row.id || i)}>
                          {result.data!.columns.map((c) => (
                            <td key={c}>
                              {row[c] === null
                                ? "Sin datos"
                                : c === "estado"
                                  ? labels[String(row[c])] || String(row[c])
                                  : String(row[c])}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty title="No hay resultados para estos filtros" />
              )}
              <Pagination
                total={result.data.total}
                offset={offset}
                limit={25}
                onChange={setOffset}
              />
            </Panel>
            <Notice>
              Los reportes por curso y recinto agrupan por estado. Sin datos
              significa metadatos ausentes; no se atribuyen recintos ni fechas
              de confirmación sin evidencia. Las exportaciones se auditan y se
              generan al solicitarlas, por lo que pueden reflejar cambios
              posteriores a esta consulta.
            </Notice>
          </>
        )
      )}
    </>
  );
}
