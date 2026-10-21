import { useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { z } from "zod";
import { api } from "../api/client";
import type { Batch, Job } from "../types";
import { Button, ErrorNotice, Field, Modal, Notice } from "./ui";
const base: Batch = {
  batch_size: 5,
  pause_seconds: 10,
  timeout_seconds: 30,
  max_retries: 3,
  retry_base_seconds: 30,
  latency_threshold_ms: 10000,
  error_threshold: 3,
  circuit_cooldown_seconds: 300,
  allowed_hours_utc: Array.from({ length: 24 }, (_, i) => i),
  max_concurrency: 1,
};
const schema = z.object({
  name: z.string().trim().min(1).max(200),
  batch_size: z.number().int().min(1).max(50),
  pause_seconds: z.number().int().min(1).max(3600),
  timeout_seconds: z.number().int().min(5).max(120),
  max_retries: z.number().int().min(0).max(5),
  retry_base_seconds: z.number().int().min(1).max(3600),
  latency_threshold_ms: z.number().int().min(100).max(120000),
  error_threshold: z.number().int().min(1).max(20),
  circuit_cooldown_seconds: z.number().int().min(30).max(3600),
  hours: z.string(),
});
type Values = z.infer<typeof schema>;
export function JobCreate({
  validationId,
  onClose,
  config,
  name = "Nueva matriculación",
}: {
  validationId: string;
  onClose: () => void;
  config?: Batch;
  name?: string;
}) {
  const defaults = { ...base, ...config };
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<Values>({
    defaultValues: {
      name,
      batch_size: defaults.batch_size,
      pause_seconds: defaults.pause_seconds,
      timeout_seconds: defaults.timeout_seconds,
      max_retries: defaults.max_retries,
      retry_base_seconds: defaults.retry_base_seconds,
      latency_threshold_ms: defaults.latency_threshold_ms,
      error_threshold: defaults.error_threshold,
      circuit_cooldown_seconds: defaults.circuit_cooldown_seconds,
      hours: defaults.allowed_hours_utc.join(","),
    },
  });
  const [error, setError] = useState<unknown>(null);
  const navigate = useNavigate();
  const client = useQueryClient();
  return (
    <Modal
      title="Configurar proceso"
      onClose={isSubmitting ? () => {} : onClose}
    >
      <Notice>
        Se creará un borrador. Las operaciones sólo se enviarán cuando inicies
        el proceso explícitamente.
      </Notice>
      <form
        onSubmit={handleSubmit(async (v) => {
          const parsed = schema.safeParse(v);
          if (!parsed.success) {
            setError(
              new Error(
                "Revisa los límites de configuración y el nombre del proceso.",
              ),
            );
            return;
          }
          const hours = v.hours
            .split(",")
            .map((h) => h.trim())
            .filter(Boolean)
            .map(Number);
          if (
            !hours.length ||
            hours.some((h) => !Number.isInteger(h) || h < 0 || h > 23) ||
            new Set(hours).size !== hours.length
          ) {
            setError(
              new Error(
                "Indica horas UTC únicas entre 0 y 23, separadas por comas.",
              ),
            );
            return;
          }
          try {
            const { name: jobName, hours: _, ...configuration } = parsed.data;
            const job = await api.post<Job>("/enrollment-jobs", {
              name: jobName,
              validation_id: validationId,
              configuration: {
                ...configuration,
                allowed_hours_utc: hours,
                max_concurrency: 1,
              },
            });
            await client.invalidateQueries();
            navigate("/jobs/" + job.id);
            onClose();
          } catch (e) {
            setError(e);
          }
        })}
      >
        <Field label="Nombre del proceso">
          <input required maxLength={200} {...register("name")} />
        </Field>
        <div className="form-grid">
          <Field label="Operaciones por lote">
            <input
              type="number"
              min={1}
              max={50}
              required
              {...register("batch_size", { valueAsNumber: true })}
            />
          </Field>
          <Field label="Pausa entre lotes (segundos)">
            <input
              type="number"
              min={1}
              max={3600}
              required
              {...register("pause_seconds", { valueAsNumber: true })}
            />
          </Field>
        </div>
        <details>
          <summary>Controles avanzados</summary>
          <div className="form-grid">
            {(
              [
                {
                  key: "timeout_seconds",
                  label: "Tiempo de respuesta (segundos)",
                  min: 5,
                  max: 120,
                },
                {
                  key: "max_retries",
                  label: "Reintentos de errores transitorios",
                  min: 0,
                  max: 5,
                },
                {
                  key: "retry_base_seconds",
                  label: "Espera base de reintento (segundos)",
                  min: 1,
                  max: 3600,
                },
                {
                  key: "latency_threshold_ms",
                  label: "Umbral de latencia (milisegundos)",
                  min: 100,
                  max: 120000,
                },
                {
                  key: "error_threshold",
                  label: "Errores consecutivos antes de suspender",
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
                  min={f.min}
                  max={f.max}
                  required
                  {...register(f.key, { valueAsNumber: true })}
                />
              </Field>
            ))}
          </div>
          <Field
            label="Horas UTC permitidas"
            hint="De 0 a 23, separadas por comas. Ejemplo: 12,13,14 equivale a 08:00–11:00 en Santo Domingo."
          >
            <input required {...register("hours")} />
          </Field>
          <p className="muted">
            Los límites de la instalación también se aplican. La capacidad debe
            calibrarse con el administrador de Moodle.
          </p>
        </details>
        <ErrorNotice error={error} />
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
            Crear borrador
          </Button>
        </div>
      </form>
    </Modal>
  );
}
