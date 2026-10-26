import { useState, type ReactNode } from "react";
import { Link, Navigate, useSearchParams } from "react-router-dom";
import { ArrowRight, LockKeyhole } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { api } from "../api/client";
import { useSession } from "../components/session";
import { Button, ErrorNotice, Field } from "../components/ui";

const emailSchema = z.object({ email: z.email("Introduce un correo válido.") });
const passwordSchema = z.object({
  password: z.string().min(12, "Usa al menos 12 caracteres.").max(128),
});

function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="login-shell">
      <div className="login-intro">
        <span className="brand-mark">M</span>
        <h1>Protege tu acceso.</h1>
        <p>
          Los enlaces de recuperación son personales, de un solo uso y caducan
          pronto.
        </p>
        <div className="login-note">
          <LockKeyhole size={18} />
          <span>Acceso reservado al personal autorizado</span>
        </div>
      </div>
      <section className="login-card">{children}</section>
    </div>
  );
}

export function PasswordResetRequest() {
  const { user } = useSession();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<{ email: string }>();
  if (user) return <Navigate replace to="/" />;
  return (
    <Shell>
      <span className="eyebrow">RECUPERAR ACCESO</span>
      <h2>Restablecer contraseña</h2>
      <p>Te enviaremos un enlace si la cuenta está activa.</p>
      {sent ? (
        <p role="status">
          Si existe una cuenta activa, recibirás instrucciones en breve.
        </p>
      ) : (
        <form
          onSubmit={handleSubmit(async (values) => {
            setError(null);
            const result = emailSchema.safeParse(values);
            if (!result.success) {
              setError(new Error(result.error.issues[0].message));
              return;
            }
            try {
              await api.post("/auth/password-reset/request", values);
              setSent(true);
            } catch (e) {
              setError(e);
            }
          })}
        >
          <Field label="Correo electrónico">
            <input
              type="email"
              autoComplete="email"
              required
              {...register("email")}
            />
          </Field>
          <ErrorNotice error={error} />
          <Button type="submit" busy={isSubmitting}>
            Enviar enlace <ArrowRight size={16} />
          </Button>
        </form>
      )}
      <small className="muted">
        <Link to="/login">Volver a iniciar sesión</Link>
      </small>
    </Shell>
  );
}

export function PasswordResetConfirm() {
  const { user } = useSession();
  const [params] = useSearchParams();
  const [done, setDone] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const token = params.get("token") || "";
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<{ password: string }>();
  if (user) return <Navigate replace to="/" />;
  return (
    <Shell>
      <span className="eyebrow">NUEVA CONTRASEÑA</span>
      <h2>Elige una contraseña nueva</h2>
      <p>Al confirmarla, se cerrarán todas tus sesiones activas.</p>
      {done ? (
        <p role="status">Contraseña actualizada. Ya puedes iniciar sesión.</p>
      ) : (
        <form
          onSubmit={handleSubmit(async (values) => {
            setError(null);
            const result = passwordSchema.safeParse(values);
            if (!token || !result.success) {
              setError(
                new Error(
                  token
                    ? result.error?.issues[0]?.message || "Valor no válido."
                    : "El enlace no es válido.",
                ),
              );
              return;
            }
            try {
              await api.post("/auth/password-reset/confirm", {
                token,
                new_password: values.password,
              });
              setDone(true);
            } catch (e) {
              setError(e);
            }
          })}
        >
          <Field label="Nueva contraseña">
            <input
              type="password"
              autoComplete="new-password"
              required
              maxLength={128}
              {...register("password")}
            />
          </Field>
          <ErrorNotice error={error} />
          <Button type="submit" busy={isSubmitting}>
            Guardar contraseña <ArrowRight size={16} />
          </Button>
        </form>
      )}
      <small className="muted">
        <Link to="/login">Volver a iniciar sesión</Link>
      </small>
    </Shell>
  );
}
