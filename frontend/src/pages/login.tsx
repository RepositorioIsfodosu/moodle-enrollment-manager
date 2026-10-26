import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Link, Navigate, useLocation } from "react-router-dom";
import { ArrowRight, LockKeyhole } from "lucide-react";
import { useSession } from "../components/session";
import { Button, ErrorNotice, Field } from "../components/ui";
const schema = z.object({
  email: z.email("Introduce un correo válido."),
  password: z.string().min(1, "Introduce la contraseña.").max(128),
});
export function Login() {
  const { user, login } = useSession();
  const location = useLocation();
  const [error, setError] = useState<unknown>(null);
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<{ email: string; password: string }>();
  if (user)
    return (
      <Navigate
        replace
        to={(location.state as { from?: string } | null)?.from || "/"}
      />
    );
  return (
    <div className="login-shell">
      <div className="login-intro">
        <span className="brand-mark">M</span>
        <h1>Matrículas bajo control.</h1>
        <p>
          Organiza tus importaciones, valida los datos y supervisa cada proceso
          desde un mismo lugar.
        </p>
        <div className="login-note">
          <LockKeyhole size={18} />
          <span>Acceso reservado al personal autorizado</span>
        </div>
      </div>
      <section className="login-card">
        <span className="eyebrow">MOODLE ENROLLMENT MANAGER</span>
        <h2>Bienvenido de nuevo</h2>
        <p>Inicia sesión para acceder a tu espacio de trabajo.</p>
        <form
          onSubmit={handleSubmit(async (values) => {
            setError(null);
            const result = schema.safeParse(values);
            if (!result.success) {
              setError(new Error(result.error.issues[0].message));
              return;
            }
            try {
              await login(values.email, values.password);
            } catch (e) {
              setError(e);
            }
          })}
        >
          <Field label="Correo electrónico">
            <input
              type="email"
              autoComplete="username"
              required
              {...register("email")}
            />
          </Field>
          <Field label="Contraseña">
            <input
              type="password"
              autoComplete="current-password"
              required
              maxLength={128}
              {...register("password")}
            />
          </Field>
          <ErrorNotice error={error} />
          <Button type="submit" busy={isSubmitting}>
            Iniciar sesión <ArrowRight size={16} />
          </Button>
        </form>
        <small className="muted">
          <Link to="/password-reset">¿Olvidaste tu contraseña?</Link>
          <br />
          Si necesitas acceso, contacta con el administrador.
        </small>
      </section>
    </div>
  );
}
