import { useEffect, useRef, useState } from "react";
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Download,
  FileSpreadsheet,
  Plus,
  Trash2,
  UploadCloud,
} from "lucide-react";
import { z } from "zod";
import { api, download, query, upload } from "../api/client";
import type {
  CsvFile,
  Import,
  Mapping,
  Operation,
  Page,
  Profile,
  Settings,
  Validation,
} from "../types";
import { useScope } from "../components/layout";
import { useSession } from "../components/session";
import {
  Badge,
  Button,
  Empty,
  ErrorNotice,
  Field,
  formatDate,
  Loading,
  Notice,
  number,
  PageTitle,
  Pagination,
  Panel,
  Progress,
} from "../components/ui";
import { OperationTable } from "../components/operation-table";
import { JobCreate } from "../components/job-create";
export function UploadBox({
  onUploaded,
}: {
  onUploaded: (file: CsvFile) => void;
}) {
  const [delimiter, setDelimiter] = useState(",");
  const [encoding, setEncoding] = useState("utf-8");
  const [progress, setProgress] = useState<{
    name: string;
    value: number;
  } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [drag, setDrag] = useState(false);
  const ref = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const settings = useQuery({
    queryKey: ["settings"],
    queryFn: ({ signal }) => api.get<Settings>("/settings", signal),
  });
  useEffect(() => () => abort.current?.abort(), []);
  const client = useQueryClient();
  async function send(files: FileList | null) {
    if (!files || progress) return;
    setError(null);
    if (files.length > 20) {
      setError(new Error("Selecciona como máximo 20 archivos por carga."));
      return;
    }
    if (!settings.data) {
      setError(
        new Error(
          "No se han podido consultar los límites de carga. Reintenta cuando estén disponibles.",
        ),
      );
      return;
    }
    abort.current = new AbortController();
    try {
      for (const file of Array.from(files)) {
        if (!file.name.toLowerCase().endsWith(".csv"))
          throw new Error("Selecciona archivos con extensión .csv.");
        if (file.size > settings.data.csv_max_bytes)
          throw new Error(
            `${file.name} supera el límite de ${Math.floor(settings.data.csv_max_bytes / 1048576)} MB.`,
          );
        setProgress({ name: file.name, value: 0 });
        const uploaded = await upload(
          file,
          delimiter,
          encoding,
          (value) => setProgress({ name: file.name, value }),
          abort.current.signal,
        );
        if (!abort.current.signal.aborted) onUploaded(uploaded);
      }
      await client.invalidateQueries({ queryKey: ["files"] });
    } catch (e) {
      if (!abort.current?.signal.aborted) setError(e);
    } finally {
      if (!abort.current?.signal.aborted) {
        setProgress(null);
        if (ref.current) ref.current.value = "";
      }
    }
  }
  return (
    <>
      <div
        className={"upload-zone " + (drag ? "drag-active" : "")}
        onDragOver={(e) => {
          e.preventDefault();
          setDrag(true);
        }}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDrag(false);
          void send(e.dataTransfer.files);
        }}
      >
        <span className="upload-icon">
          <UploadCloud size={25} />
        </span>
        <strong>Arrastra tus archivos CSV aquí</strong>
        <p>o selecciónalos desde tu equipo</p>
        <Button
          type="button"
          variant="secondary"
          busy={!!progress}
          disabled={!settings.data}
          onClick={() => ref.current?.click()}
        >
          Seleccionar archivos
        </Button>
        <input
          ref={ref}
          className="visually-hidden"
          aria-label="Seleccionar archivos CSV"
          type="file"
          accept=".csv,text/csv"
          multiple
          disabled={!!progress || !settings.data}
          onChange={(e) => void send(e.target.files)}
        />
        <small>
          {settings.data
            ? `Hasta ${Math.floor(settings.data.csv_max_bytes / 1048576)} MB por archivo · UTF-8 / UTF-8 BOM`
            : "Consultando límites de carga…"}
        </small>
      </div>
      <div className="form-grid upload-options">
        <Field label="Delimitador">
          <select
            value={delimiter}
            disabled={!!progress}
            onChange={(e) => setDelimiter(e.target.value)}
          >
            <option value=",">Coma (,)</option>
            <option value=";">Punto y coma (;)</option>
            <option value={"\t"}>Tabulador</option>
            <option value="|">Barra vertical (|)</option>
          </select>
        </Field>
        <Field label="Codificación">
          <select
            value={encoding}
            disabled={!!progress}
            onChange={(e) => setEncoding(e.target.value)}
          >
            <option value="utf-8">UTF-8 con o sin BOM</option>
            <option value="cp1252">Windows-1252</option>
            <option value="latin-1">Latin-1</option>
          </select>
        </Field>
      </div>
      {progress && (
        <div className="upload-progress" role="status">
          <span>
            {progress.name} ·{" "}
            {progress.value === 100 ? "Comprobando archivo…" : "Enviando…"}
          </span>
          <Progress value={progress.value} />
        </div>
      )}
      <ErrorNotice error={error || settings.error} />
    </>
  );
}
export function Files() {
  const [offset, setOffset] = useState(0);
  const [added, setAdded] = useState<CsvFile[]>([]);
  const [error, setError] = useState<unknown>(null);
  const { can } = useSession();
  const files = useQuery({
    queryKey: ["files", offset],
    queryFn: ({ signal }) =>
      api.get<Page<CsvFile>>(
        "/csv-files" + query({ offset, limit: 25 }),
        signal,
      ),
  });
  return (
    <>
      <PageTitle
        title="Archivos CSV"
        description="Conserva el origen de tus datos y revisa cada importación."
      />
      {can("imports:write") && (
        <Panel title="Cargar archivos">
          <UploadBox
            onUploaded={(f) => {
              setAdded((previous) => [...previous, f]);
            }}
          />
          {added.length > 0 && (
            <div className="uploaded-list">
              {added.map((f) => (
                <Link key={f.id} to={"/files/" + f.id}>
                  <Check size={15} />
                  {f.original_name}
                  <ArrowRight size={15} />
                </Link>
              ))}
            </div>
          )}
        </Panel>
      )}
      <Panel title="Historial de archivos">
        <ErrorNotice error={files.error || error} />
        {files.isPending ? (
          <Loading />
        ) : files.data?.items.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Archivo</th>
                  <th>Filas</th>
                  <th>Tamaño</th>
                  <th>Fecha</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {files.data.items.map((f) => (
                  <tr key={f.id}>
                    <td>
                      <Link className="row-link" to={"/files/" + f.id}>
                        <FileSpreadsheet size={16} />
                        {f.original_name}
                      </Link>
                    </td>
                    <td>{number(f.row_count)}</td>
                    <td>{(f.byte_count / 1024).toFixed(1)} KB</td>
                    <td>{formatDate(f.created_at)}</td>
                    <td>
                      <Button
                        variant="ghost"
                        aria-label={"Descargar " + f.original_name}
                        onClick={() => {
                          void download(
                            `/csv-files/${f.id}/original`,
                            f.original_name,
                          ).catch(setError);
                        }}
                      >
                        <Download size={16} />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="Aún no has cargado archivos" />
        )}
        <Pagination
          offset={offset}
          total={files.data?.total || 0}
          limit={25}
          onChange={setOffset}
        />
      </Panel>
    </>
  );
}
function Preview({ file }: { file: CsvFile }) {
  return (
    <div className="table-wrap preview-table">
      <table>
        <thead>
          <tr>
            {file.headers.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {file.preview.map((row, i) => (
            <tr key={i}>
              {file.headers.map((h) => (
                <td key={h}>{row[h] || "—"}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="table-note">
        Vista previa de {file.preview.length} filas; el archivo contiene{" "}
        {number(file.row_count)} filas de datos.
      </div>
    </div>
  );
}
function initial(file: CsvFile): Mapping {
  const user =
    file.headers.find((h) => ["username", "email", "idnumber"].includes(h)) ||
    "";
  return {
    user_column: user,
    user_field:
      user === "email"
        ? "email"
        : user === "idnumber"
          ? "idnumber"
          : "username",
    course_field: "shortname",
    group_field: "name",
    courses: file.headers
      .filter((h) => /^course\d+$/.test(h))
      .map((course) => ({
        course,
        role: file.headers.includes(course.replace("course", "role"))
          ? course.replace("course", "role")
          : null,
        group: file.headers.includes(course.replace("course", "group"))
          ? course.replace("course", "group")
          : null,
      })),
    default_role_id: null,
    role_map: {},
    metadata_columns: {},
  };
}
export function FileMapping({
  file,
  onNormalized,
}: {
  file: CsvFile;
  onNormalized: (result: Import) => void;
}) {
  const [mapping, setMapping] = useState<Mapping>(() => initial(file));
  const [roleMap, setRoleMap] = useState("{}");
  const [profileName, setProfileName] = useState("");
  const [profileId, setProfileId] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState("");
  const client = useQueryClient();
  const profiles = useQuery({
    queryKey: ["profiles"],
    queryFn: ({ signal }) =>
      api.get<Page<Profile>>("/import-profiles?limit=100", signal),
  });
  const mutation = useMutation({
    mutationFn: async () => {
      let parsed: unknown;
      try {
        parsed = JSON.parse(roleMap);
      } catch {
        throw new Error("El mapa de roles debe tener formato JSON válido.");
      }
      const result = z
        .record(z.string().min(1), z.number().int().min(1).max(2147483647))
        .safeParse(parsed);
      if (!result.success)
        throw new Error(
          "El mapa de roles debe asociar cada valor a un ID entero positivo.",
        );
      if (
        !mapping.user_column ||
        !mapping.courses.length ||
        mapping.courses.some((c) => !c.course)
      )
        throw new Error(
          "Selecciona la columna de usuario y al menos un curso.",
        );
      const payload = { ...mapping, role_map: result.data };
      return api.post<Import>(`/csv-files/${file.id}/normalize`, {
        mapping: payload,
      });
    },
    onSuccess: async (result) => {
      onNormalized(result);
      await client.invalidateQueries({ queryKey: ["imports"] });
    },
  });
  const save = useMutation({
    mutationFn: async () => {
      if (!profileName.trim())
        throw new Error("Indica un nombre para el perfil.");
      const parsed = z
        .record(z.string(), z.number().int().positive())
        .safeParse(JSON.parse(roleMap));
      if (!parsed.success) throw new Error("Mapa de roles no válido.");
      const body = {
        name: profileName.trim(),
        mapping: { ...mapping, role_map: parsed.data },
      };
      return profileId
        ? api.put<Profile>("/import-profiles/" + profileId, body)
        : api.post<Profile>("/import-profiles", body);
    },
    onSuccess: async (profile) => {
      setSuccess("Perfil guardado.");
      setProfileName(profile.name);
      setProfileId(profile.id);
      await client.invalidateQueries({ queryKey: ["profiles"] });
    },
  });
  const set = <K extends keyof Mapping>(key: K, value: Mapping[K]) => {
    setMapping((previous) => ({ ...previous, [key]: value }));
  };
  const column = (
    value: string | null,
    onChange: (value: string | null) => void,
    required = false,
  ) => (
    <select
      value={value || ""}
      required={required}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">
        {required ? "Seleccionar columna" : "No utilizar"}
      </option>
      {file.headers.map((h) => (
        <option key={h} value={h}>
          {h}
        </option>
      ))}
    </select>
  );
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        setError(null);
        setSuccess("");
        mutation.mutate();
      }}
    >
      <Field label="Aplicar perfil guardado">
        <select
          value={profileId}
          onChange={(e) => {
            setProfileId(e.target.value);
            const p = profiles.data?.items.find((p) => p.id === e.target.value);
            if (p) {
              const copied = structuredClone(p.mapping);
              setMapping({
                ...copied,
                user_column: copied.user_column || initial(file).user_column,
                courses: copied.courses.length
                  ? copied.courses
                  : initial(file).courses,
              });
              setProfileName(p.name);
              setRoleMap(JSON.stringify(p.mapping.role_map));
            }
          }}
        >
          <option value="">Mapeo personalizado</option>
          {profiles.data?.items.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </Field>
      <div className="form-grid">
        <Field label="Columna de usuario">
          {column(mapping.user_column, (v) => set("user_column", v), true)}
        </Field>
        <Field label="Identificador de usuario Moodle">
          <select
            value={mapping.user_field}
            onChange={(e) =>
              set("user_field", e.target.value as Mapping["user_field"])
            }
          >
            <option value="username">Nombre de usuario (username)</option>
            <option value="email">Correo electrónico (email)</option>
            <option value="idnumber">
              Número de identificación (idnumber)
            </option>
          </select>
        </Field>
        <Field label="Identificador de curso">
          <select
            value={mapping.course_field}
            onChange={(e) =>
              set("course_field", e.target.value as Mapping["course_field"])
            }
          >
            <option value="shortname">Nombre corto (shortname)</option>
            <option value="id">ID interno</option>
            <option value="idnumber">Identificador (idnumber)</option>
          </select>
        </Field>
        <Field label="Identificador de grupo">
          <select
            value={mapping.group_field}
            onChange={(e) =>
              set("group_field", e.target.value as Mapping["group_field"])
            }
          >
            <option value="name">Nombre</option>
            <option value="id">ID interno</option>
            <option value="idnumber">Identificador (idnumber)</option>
          </select>
        </Field>
      </div>
      <div className="mapping-title">
        <h3>Cursos, roles y grupos</h3>
        <Button
          type="button"
          variant="ghost"
          disabled={mapping.courses.length >= 50}
          onClick={() =>
            set("courses", [
              ...mapping.courses,
              { course: "", role: null, group: null },
            ])
          }
        >
          <Plus size={15} />
          Agregar curso
        </Button>
      </div>
      {mapping.courses.map((course, i) => (
        <div className="mapping-row" key={i}>
          <Field label={"Curso " + (i + 1)}>
            {column(
              course.course,
              (v) =>
                set(
                  "courses",
                  mapping.courses.map((c, n) =>
                    n === i ? { ...c, course: v || "" } : c,
                  ),
                ),
              true,
            )}
          </Field>
          <Field label={"Rol " + (i + 1)}>
            {column(course.role, (v) =>
              set(
                "courses",
                mapping.courses.map((c, n) =>
                  n === i ? { ...c, role: v } : c,
                ),
              ),
            )}
          </Field>
          <Field label={"Grupo " + (i + 1)}>
            {column(course.group, (v) =>
              set(
                "courses",
                mapping.courses.map((c, n) =>
                  n === i ? { ...c, group: v } : c,
                ),
              ),
            )}
          </Field>
          <Button
            variant="ghost"
            type="button"
            aria-label={"Quitar curso " + (i + 1)}
            onClick={() =>
              set(
                "courses",
                mapping.courses.filter((_, n) => n !== i),
              )
            }
          >
            <Trash2 size={16} />
          </Button>
        </div>
      ))}
      <Field
        label="Rol predeterminado (opcional)"
        hint="ID del rol aprobado por tu administrador. No se asigna un rol por defecto si lo dejas vacío."
      >
        <input
          type="number"
          min={1}
          max={2147483647}
          value={mapping.default_role_id ?? ""}
          onChange={(e) =>
            set(
              "default_role_id",
              e.target.value ? Number(e.target.value) : null,
            )
          }
        />
      </Field>
      <details>
        <summary>Metadatos y mapeo de roles</summary>
        <div className="form-grid">
          <Field label="Columna de período académico">
            {column(mapping.metadata_columns.period || null, (v) =>
              set(
                "metadata_columns",
                v
                  ? { ...mapping.metadata_columns, period: v }
                  : Object.fromEntries(
                      Object.entries(mapping.metadata_columns).filter(
                        ([k]) => k !== "period",
                      ),
                    ),
              ),
            )}
          </Field>
          <Field label="Columna de recinto">
            {column(mapping.metadata_columns.campus || null, (v) =>
              set(
                "metadata_columns",
                v
                  ? { ...mapping.metadata_columns, campus: v }
                  : Object.fromEntries(
                      Object.entries(mapping.metadata_columns).filter(
                        ([k]) => k !== "campus",
                      ),
                    ),
              ),
            )}
          </Field>
        </div>
        <Field
          label="Mapa explícito de roles (JSON)"
          hint="Asocia los valores del CSV a IDs de roles verificados; deja {} si el CSV ya utiliza IDs."
        >
          <textarea
            value={roleMap}
            onChange={(e) => setRoleMap(e.target.value)}
            rows={3}
          />
        </Field>
        <div className="inline-form">
          <Field label="Nombre para guardar este perfil">
            <input
              maxLength={200}
              value={profileName}
              onChange={(e) => setProfileName(e.target.value)}
            />
          </Field>
          <Button
            type="button"
            variant="secondary"
            busy={save.isPending}
            disabled={!profileName.trim()}
            onClick={() => save.mutate()}
          >
            {profileId ? "Guardar cambios del perfil" : "Guardar perfil"}
          </Button>
        </div>
        {success && (
          <p className="success-text" role="status">
            {success}
          </p>
        )}
      </details>
      <ErrorNotice
        error={error || mutation.error || save.error || profiles.error}
      />
      <div className="actions">
        <Button type="submit" busy={mutation.isPending}>
          Analizar y normalizar <ArrowRight size={15} />
        </Button>
      </div>
    </form>
  );
}
export function FileDetail() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const { can } = useSession();
  const [offset, setOffset] = useState(0);
  const file = useQuery({
    queryKey: ["file", id],
    queryFn: ({ signal }) => api.get<CsvFile>("/csv-files/" + id, signal),
  });
  const imports = useQuery({
    queryKey: ["imports", id],
    queryFn: ({ signal }) =>
      api.get<Page<Import>>(
        "/csv-imports" + query({ file_id: id, limit: 100 }),
        signal,
      ),
  });
  const selected = params.get("import") || imports.data?.items[0]?.id;
  const operations = useQuery({
    queryKey: ["operations", selected, offset],
    queryFn: ({ signal }) =>
      api.get<Page<Operation>>(
        `/csv-imports/${selected}/operations` + query({ offset, limit: 50 }),
        signal,
      ),
    enabled: !!selected,
  });
  useEffect(() => setOffset(0), [selected]);
  if (file.isPending) return <Loading />;
  if (!file.data) return <ErrorNotice error={file.error} />;
  return (
    <>
      <Link className="back-link" to="/files">
        <ArrowLeft size={15} />
        Archivos CSV
      </Link>
      <PageTitle
        title={file.data.original_name}
        description={`${number(file.data.row_count)} filas · ${file.data.encoding} · Archivo original conservado`}
      />
      <Panel title="Vista previa">
        <Preview file={file.data} />
      </Panel>
      {can("imports:write") && (
        <Panel title="Mapeo de columnas">
          <FileMapping
            key={id}
            file={file.data}
            onNormalized={(entry) => setParams({ import: entry.id })}
          />
        </Panel>
      )}
      <Panel
        title="Operaciones normalizadas"
        action={
          <Link className="text-link" to="/new">
            Validar una importación <ArrowRight size={15} />
          </Link>
        }
      >
        <ErrorNotice error={imports.error || operations.error} />
        {imports.data?.items.length ? (
          <Field label="Versión de importación">
            <select
              value={selected || ""}
              onChange={(e) => setParams({ import: e.target.value })}
            >
              {imports.data.items.map((r, i) => (
                <option key={r.id} value={r.id}>
                  Versión {imports.data!.items.length - i} · {r.operation_count}{" "}
                  operaciones
                </option>
              ))}
            </select>
          </Field>
        ) : (
          <Empty title="Analiza el archivo para generar operaciones" />
        )}
        {selected && (
          <>
            <OperationTable rows={operations.data?.items || []} />
            <Pagination
              offset={offset}
              total={operations.data?.total || 0}
              limit={50}
              onChange={setOffset}
            />
          </>
        )}
      </Panel>
    </>
  );
}
export function NewEnrollment() {
  const { connection, setConnection, destinations } = useScope();
  const [files, setFiles] = useState<CsvFile[]>([]);
  const [active, setActive] = useState("");
  const [selected, setSelected] = useState(new Set<string>());
  const [offset, setOffset] = useState(0);
  const navigate = useNavigate();
  const imports = useQuery({
    queryKey: ["imports", offset],
    queryFn: ({ signal }) =>
      api.get<Page<Import>>(
        "/csv-imports" + query({ offset, limit: 25 }),
        signal,
      ),
  });
  const validation = useMutation({
    mutationFn: () => {
      if (!connection)
        throw new Error("Selecciona la instalación Moodle de destino.");
      if (!selected.size || selected.size > 20)
        throw new Error("Selecciona entre 1 y 20 importaciones.");
      return api.post<Validation>("/validations", {
        connection_id: connection,
        import_ids: [...selected],
      });
    },
    onSuccess: (v) => navigate("/validations/" + v.id),
  });
  const current = files.find((f) => f.id === active);
  return (
    <>
      <PageTitle
        title="Nueva matriculación"
        description="Prepara los archivos, revisa sus columnas y valida antes de ejecutar."
      />
      <div className="stepper">
        <span>
          <b>1</b>Cargar archivos
        </span>
        <span>
          <b>2</b>Mapear columnas
        </span>
        <span>
          <b>3</b>Validar operaciones
        </span>
      </div>
      <Panel title="1. Carga tus archivos CSV">
        <UploadBox
          onUploaded={(f) => {
            setFiles((previous) => [...previous, f]);
            setActive(f.id);
          }}
        />
        <div className="uploaded-list">
          {files.map((f) => (
            <button
              className={f.id === active ? "active" : ""}
              key={f.id}
              onClick={() => setActive(f.id)}
            >
              <FileSpreadsheet size={15} />
              {f.original_name}
              <small>{f.row_count} filas</small>
            </button>
          ))}
        </div>
        <p className="muted">
          ¿Ya cargaste el archivo? Puedes{" "}
          <Link to="/files">abrirlo desde Archivos CSV</Link> y conservar sus
          versiones.
        </p>
      </Panel>
      {current && (
        <Panel title={"2. Mapea " + current.original_name}>
          <Preview file={current} />
          <FileMapping
            key={current.id}
            file={current}
            onNormalized={(entry) =>
              setSelected((previous) => new Set([...previous, entry.id]))
            }
          />
        </Panel>
      )}
      <Panel title="3. Selecciona importaciones y valida">
        <Notice>
          Una fila puede generar varias operaciones. La validación comprueba
          datos y permisos; no ejecuta matrículas.
        </Notice>
        <Field label="Instalación Moodle de destino">
          <select
            required
            value={connection}
            onChange={(e) => setConnection(e.target.value)}
          >
            <option value="">Seleccionar instalación</option>
            {destinations.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
        <ErrorNotice error={imports.error || validation.error} />
        {imports.isPending ? (
          <Loading />
        ) : imports.data?.items.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Elegir</th>
                  <th>Archivo</th>
                  <th>Operaciones</th>
                  <th>Inválidas</th>
                  <th>Duplicadas</th>
                  <th>Creado</th>
                </tr>
              </thead>
              <tbody>
                {imports.data.items.map((entry) => (
                  <tr key={entry.id}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label={
                          "Seleccionar importación " + entry.original_name
                        }
                        checked={selected.has(entry.id)}
                        onChange={() =>
                          setSelected((previous) => {
                            const next = new Set(previous);
                            if (next.has(entry.id)) next.delete(entry.id);
                            else next.add(entry.id);
                            return next;
                          })
                        }
                      />
                    </td>
                    <td>
                      <Link
                        to={"/files/" + entry.file_id + "?import=" + entry.id}
                      >
                        {entry.original_name || entry.file_id}
                      </Link>
                    </td>
                    <td>{entry.operation_count}</td>
                    <td>{entry.counts.invalid || 0}</td>
                    <td>{entry.counts.duplicate || 0}</td>
                    <td>{formatDate(entry.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty title="Todavía no hay importaciones normalizadas">
            Carga un CSV y analiza su mapeo de columnas.
          </Empty>
        )}
        <Pagination
          offset={offset}
          total={imports.data?.total || 0}
          limit={25}
          onChange={setOffset}
        />
        <div className="actions">
          <span className="muted">
            {selected.size} de 20 importaciones seleccionadas
          </span>
          <Button
            busy={validation.isPending}
            disabled={!selected.size || selected.size > 20 || !connection}
            onClick={() => validation.mutate()}
          >
            Validar operaciones <ArrowRight size={15} />
          </Button>
        </div>
      </Panel>
      <ValidationHistory />
    </>
  );
}
export function ValidationHistory() {
  const [offset, setOffset] = useState(0);
  const rows = useQuery({
    queryKey: ["validations", offset],
    queryFn: ({ signal }) =>
      api.get<Page<Validation>>(
        "/validations" + query({ offset, limit: 25 }),
        signal,
      ),
    refetchInterval: 5000,
  });
  return (
    <Panel title="Validaciones anteriores">
      <ErrorNotice error={rows.error} />
      {rows.data?.items.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Estado</th>
                <th>Operaciones</th>
                <th>Progreso</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.data.items.map((r) => (
                <tr key={r.id}>
                  <td>{formatDate(r.created_at)}</td>
                  <td>
                    <Badge state={r.state} />
                  </td>
                  <td>{number(r.total)}</td>
                  <td>
                    <Progress value={r.progress_percent} />
                  </td>
                  <td>
                    <Link className="text-link" to={"/validations/" + r.id}>
                      Revisar <ArrowRight size={15} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : rows.isPending ? (
        <Loading />
      ) : (
        <Empty />
      )}
      <Pagination
        offset={offset}
        total={rows.data?.total || 0}
        limit={25}
        onChange={setOffset}
      />
    </Panel>
  );
}
export function ValidationDetail() {
  const { id = "" } = useParams();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [create, setCreate] = useState(false);
  const { can } = useSession();
  const client = useQueryClient();
  const run = useQuery({
    queryKey: ["validation", id],
    queryFn: ({ signal }) => api.get<Validation>("/validations/" + id, signal),
    refetchInterval: 5000,
  });
  const records = useQuery({
    queryKey: ["validation-records", id, status, offset],
    queryFn: ({ signal }) =>
      api.get<Page<Operation>>(
        `/validations/${id}/records` + query({ status, offset, limit: 50 }),
        signal,
      ),
    refetchInterval: 5000,
  });
  const cancel = useMutation({
    mutationFn: () => api.post(`/validations/${id}/cancel`),
    onSuccess: () => client.invalidateQueries(),
  });
  useEffect(() => setOffset(0), [status, id]);
  if (run.isPending) return <Loading />;
  if (!run.data) return <ErrorNotice error={run.error} />;
  const v = run.data;
  const eligible =
    v.state === "completed" &&
    !v.counts.invalid &&
    !v.counts.pending &&
    (v.counts.valid || 0) + (v.counts.existing || 0) > 0;
  return (
    <>
      <Link className="back-link" to="/new">
        <ArrowLeft size={15} />
        Nueva matriculación
      </Link>
      <PageTitle
        title="Validación de operaciones"
        description={"Creada el " + formatDate(v.created_at)}
        action={
          <div className="actions">
            {can("imports:write") &&
              ["queued", "running"].includes(v.state) && (
                <Button
                  variant="danger"
                  busy={cancel.isPending}
                  onClick={() => cancel.mutate()}
                >
                  Cancelar validación
                </Button>
              )}
            {can("jobs:write") && (
              <Button disabled={!eligible} onClick={() => setCreate(true)}>
                Configurar proceso <ArrowRight size={15} />
              </Button>
            )}
          </div>
        }
      />
      <ErrorNotice error={run.error || cancel.error} />
      {v.error_code && <ErrorNotice error={new Error(v.error_code)} />}
      <div className="process-banner">
        <div>
          <Badge state={v.state} />
          <span>
            {v.checked} de {v.total} operaciones revisadas
          </span>
        </div>
        <Progress value={v.progress_percent} />
      </div>
      <Notice>
        Terminar el análisis no confirma matrículas. Corrige los registros
        inválidos y los pendientes antes de crear un proceso. La existencia de
        un rol o la visibilidad incompleta puede requerir revisión
        administrativa.
      </Notice>
      <div className="stats-grid">
        {["valid", "invalid", "duplicate", "existing", "pending"].map((s) => (
          <div key={s} className="stat-card compact">
            <Badge state={s} />
            <strong>{number(v.counts[s] || 0)}</strong>
          </div>
        ))}
      </div>
      <Panel title="Resultado por operación">
        <div className="toolbar">
          <Field label="Clasificación">
            <select value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Todas</option>
              {["valid", "invalid", "duplicate", "existing", "pending"].map(
                (s) => (
                  <option key={s} value={s}>
                    {s === "valid"
                      ? "Válidas"
                      : s === "invalid"
                        ? "Inválidas"
                        : s === "duplicate"
                          ? "Duplicadas"
                          : s === "existing"
                            ? "Ya matriculadas"
                            : "Pendientes de comprobación"}
                  </option>
                ),
              )}
            </select>
          </Field>
        </div>
        <ErrorNotice error={records.error} />
        {records.isPending ? (
          <Loading />
        ) : (
          <OperationTable rows={records.data?.items || []} />
        )}
        <Pagination
          offset={offset}
          total={records.data?.total || 0}
          limit={50}
          onChange={setOffset}
        />
      </Panel>
      {create && (
        <JobCreate validationId={id} onClose={() => setCreate(false)} />
      )}
    </>
  );
}
