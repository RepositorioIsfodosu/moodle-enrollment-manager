import type { Operation } from "../types";
import { Badge, Empty } from "./ui";
export function OperationTable({
  rows,
  selected,
  onToggle,
}: {
  rows: Operation[];
  selected?: Set<string>;
  onToggle?: (id: string) => void;
}) {
  if (!rows.length) return <Empty />;
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {onToggle && <th>Elegir</th>}
            <th>Fila</th>
            <th>Usuario</th>
            <th>Curso</th>
            <th>Rol</th>
            <th>Estado</th>
            <th>Detalle</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              {onToggle && (
                <td>
                  <input
                    type="checkbox"
                    aria-label={"Seleccionar fila " + r.source_row}
                    checked={selected?.has(r.id) || false}
                    disabled={!r.retryable}
                    onChange={() => onToggle(r.id)}
                  />
                </td>
              )}
              <td>
                {r.source_row}
                {r.slot ? ` · ${r.slot}` : ""}
              </td>
              <td>
                {r.user_identifier || String(r.payload?.user_identifier || "—")}
              </td>
              <td>
                {r.course_identifier ||
                  String(r.payload?.course_identifier || "—")}
              </td>
              <td>{r.role_id || String(r.payload?.role_id || "—")}</td>
              <td>
                <Badge state={r.state || r.status || "pending"} />
              </td>
              <td className="detail-text">{r.reason || r.error_code || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
