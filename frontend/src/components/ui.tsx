import {
  cloneElement,
  isValidElement,
  useId,
  type ReactElement,
  useEffect,
  useRef,
  type ReactNode,
  type ButtonHTMLAttributes,
} from "react";
import {
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  LoaderCircle,
  X,
} from "lucide-react";
export const labels: Record<string, string> = {
  draft: "Borrador",
  validating: "Validando",
  ready: "Listo",
  queued: "En cola",
  running: "En ejecución",
  pausing: "Pausando",
  paused: "Pausado",
  completed: "Completado",
  completed_with_errors: "Completado con incidencias",
  failed: "Fallido",
  cancelling: "Cancelando",
  cancelled: "Cancelado",
  pending: "Pendiente",
  reserved: "En curso",
  confirmed: "Confirmada",
  existing: "Existente",
  uncertain: "Incierta",
  skipped: "Omitida",
  valid: "Válido",
  invalid: "Inválido",
  duplicate: "Duplicado",
  verified: "Verificada",
  unverified: "Sin verificar",
  limited: "Funciones limitadas",
  error: "Error",
  disabled: "Desactivada",
  write_intent: "Intención de envío",
  accepted_unconfirmed: "Respuesta recibida; sin confirmar",
  confirmed_by_observation: "Confirmada por lectura",
  not_dispatched: "No enviada",
};
export function Badge({ state }: { state: string }) {
  return (
    <span className={"badge badge-" + state}>{labels[state] || state}</span>
  );
}
export function Button({
  children,
  variant = "primary",
  busy = false,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  busy?: boolean;
}) {
  return (
    <button
      {...props}
      disabled={props.disabled || busy}
      className={"btn btn-" + variant + " " + (props.className || "")}
    >
      {busy && <LoaderCircle size={15} className="spin" />}
      {children}
    </button>
  );
}
export function ErrorNotice({ error }: { error: unknown }) {
  return error ? (
    <div className="notice error" role="alert">
      <AlertCircle size={18} />
      <span>{error instanceof Error ? error.message : String(error)}</span>
    </div>
  ) : null;
}
export function Notice({ children }: { children: ReactNode }) {
  return <div className="notice">{children}</div>;
}
export function Empty({
  title = "Todavía no hay registros",
  children,
}: {
  title?: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      <p>
        {children || "Los resultados aparecerán aquí cuando estén disponibles."}
      </p>
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle size={20} className="spin" /> Cargando datos…
    </div>
  );
}
export function PageTitle({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <span className="eyebrow">
          {eyebrow || "MOODLE ENROLLMENT MANAGER"}
        </span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action}
    </div>
  );
}
export function Panel({
  title,
  children,
  action,
}: {
  title?: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="panel">
      {title && (
        <div className="panel-heading">
          <h2>{title}</h2>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault();
        onClose();
      }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button
          className="icon-btn"
          onClick={onClose}
          aria-label="Cerrar diálogo"
        >
          <X size={19} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Confirm({
  title,
  children,
  onClose,
  onConfirm,
  busy,
  error,
}: {
  title: string;
  children: ReactNode;
  onClose: () => void;
  onConfirm: () => void;
  busy: boolean;
  error: unknown;
}) {
  return (
    <Modal title={title} onClose={busy ? () => {} : onClose}>
      <p>{children}</p>
      <ErrorNotice error={error} />
      <div className="actions">
        <Button variant="secondary" onClick={onClose} disabled={busy}>
          Volver
        </Button>
        <Button busy={busy} onClick={onConfirm}>
          Confirmar
        </Button>
      </div>
    </Modal>
  );
}
export function Pagination({
  offset,
  total,
  limit,
  onChange,
}: {
  offset: number;
  total: number;
  limit: number;
  onChange: (n: number) => void;
}) {
  return (
    <div className="pagination">
      <span>
        {total
          ? `${offset + 1}–${Math.min(offset + limit, total)} de ${total.toLocaleString("es-DO")}`
          : "0 registros"}
      </span>
      <div>
        <Button
          variant="ghost"
          onClick={() => onChange(Math.max(0, offset - limit))}
          disabled={offset === 0}
          aria-label="Página anterior"
        >
          <ChevronLeft size={16} />
        </Button>
        <Button
          variant="ghost"
          onClick={() => onChange(offset + limit)}
          disabled={offset + limit >= total}
          aria-label="Página siguiente"
        >
          <ChevronRight size={16} />
        </Button>
      </div>
    </div>
  );
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  const id = useId();
  const control = isValidElement(children)
    ? cloneElement(
        children as ReactElement<{
          "aria-labelledby"?: string;
          "aria-describedby"?: string;
        }>,
        {
          "aria-labelledby": id + "-label",
          "aria-describedby": hint ? id + "-hint" : undefined,
        },
      )
    : children;
  return (
    <label className="field">
      <span id={id + "-label"}>{label}</span>
      {control}
      {hint && <small id={id + "-hint"}>{hint}</small>}
    </label>
  );
}
export function Progress({ value }: { value: number }) {
  return (
    <div className="progress-row">
      <progress max={100} value={value} aria-label="Progreso" />
      <span>{value.toFixed(1)}%</span>
    </div>
  );
}
export function formatDate(
  value?: string | null,
  zone = "America/Santo_Domingo",
) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("es-DO", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: zone,
  }).format(new Date(value));
}
export function number(value?: number | null) {
  return value === null || value === undefined
    ? "—"
    : value.toLocaleString("es-DO");
}
