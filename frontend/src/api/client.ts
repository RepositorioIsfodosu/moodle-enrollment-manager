export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}
function failure(status: number, detail: unknown): ApiError {
  if (status === 401) window.dispatchEvent(new Event("session-expired"));
  return new ApiError(
    status,
    typeof detail === "string"
      ? detail
      : status === 422
        ? "Revisa los campos: hay valores no válidos."
        : status === 403
          ? "No tienes permiso para esta operación."
          : status === 404
            ? "El recurso no está disponible o no tienes acceso."
            : status === 429
              ? "Se alcanzó el límite de solicitudes. Espera antes de reintentar."
              : "No se pudo completar la solicitud. Inténtalo de nuevo.",
  );
}
async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api/v1" + path, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      signal,
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Protection": "1",
        ...(path === "/auth/login" ? { "X-Session-Mode": "cookie" } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "No se pudo contactar con el servidor. Comprueba tu conexión.",
    );
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw failure(response.status, data.detail);
  }
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}
export const api = {
  get: <T>(p: string, s?: AbortSignal) => request<T>(p, "GET", undefined, s),
  post: <T>(p: string, b?: unknown) => request<T>(p, "POST", b),
  patch: <T>(p: string, b: unknown) => request<T>(p, "PATCH", b),
  put: <T>(p: string, b: unknown) => request<T>(p, "PUT", b),
  delete: <T>(p: string) => request<T>(p, "DELETE"),
};
export function query(
  values: Record<string, string | number | boolean | null | undefined>,
) {
  const q = new URLSearchParams();
  Object.entries(values).forEach(([k, v]) => {
    if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  });
  return q.size ? "?" + q.toString() : "";
}
export function upload(
  file: File,
  delimiter: string,
  encoding: string,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
) {
  return new Promise<import("../types").CsvFile>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(
      "POST",
      "/api/v1/csv-files" + query({ filename: file.name, delimiter, encoding }),
    );
    xhr.withCredentials = true;
    xhr.timeout = 120000;
    xhr.setRequestHeader("Content-Type", "text/csv");
    xhr.setRequestHeader("X-CSRF-Protection", "1");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable)
        onProgress(Math.round((100 * e.loaded) / e.total));
    };
    xhr.onerror = () =>
      reject(
        new ApiError(0, "Se interrumpió la carga. Comprueba tu conexión."),
      );
    xhr.ontimeout = () =>
      reject(new ApiError(0, "La carga superó el tiempo de espera."));
    xhr.onabort = () => reject(new ApiError(0, "Carga cancelada."));
    const abort = () => xhr.abort();
    signal?.addEventListener("abort", abort, { once: true });
    xhr.onloadend = () => signal?.removeEventListener("abort", abort);
    xhr.onload = () => {
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        reject(new ApiError(xhr.status, "Respuesta de carga no válida."));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(failure(xhr.status, data.detail));
    };
    xhr.send(file);
  });
}
export async function download(path: string, name: string) {
  const response = await fetch("/api/v1" + path, {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!response.ok)
    throw failure(
      response.status,
      (await response.json().catch(() => ({}))).detail,
    );
  const url = URL.createObjectURL(await response.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
