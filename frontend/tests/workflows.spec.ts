import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
const seed = JSON.parse(
  fs.readFileSync(process.env.E2E_SEED_PATH!, "utf8"),
) as {
  email: string;
  reader: string;
  password: string;
  connection_id: string;
  validation_id: string;
};
async function login(page: Page, email = seed.email) {
  await page.goto("/login");
  await page.getByLabel("Correo electrónico", { exact: true }).fill(email);
  await page.getByLabel("Contraseña", { exact: true }).fill(seed.password);
  await page.getByRole("button", { name: "Iniciar sesión" }).click();
  await expect(
    page.getByRole("heading", { name: "Vista general", exact: true }),
  ).toBeVisible();
}

test("sesión HttpOnly, recarga y cierre sin token en almacenamiento del navegador", async ({
  page,
  context,
}) => {
  await login(page);
  expect(
    (await context.cookies()).find((c) => c.name === "mem_session")?.httpOnly,
  ).toBe(true);
  expect(await page.evaluate(() => document.cookie)).not.toContain(
    "mem_session",
  );
  expect(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
  ).toBe(0);
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Vista general", exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/screens/dashboard.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Cerrar sesión", exact: true })
    .click();
  await expect(page).toHaveURL(/\/login$/);
  await page.goto("/jobs");
  await expect(page).toHaveURL(/\/login$/);
});

test("CSV real: carga, mapeo, persistencia y validación local con worker", async ({
  page,
}) => {
  await login(page);
  await page
    .getByRole("link", { name: "Nueva matriculación", exact: true })
    .first()
    .click();
  await expect(
    page.getByLabel("Seleccionar archivos CSV", { exact: true }),
  ).toBeEnabled();
  await page
    .getByLabel("Seleccionar archivos CSV", { exact: true })
    .setInputFiles({
      name: "browser-invalid.csv",
      mimeType: "text/csv",
      buffer: Buffer.from("username,course1,role1\nalice,BIO,not-a-role\n"),
    });
  await expect(
    page.getByRole("heading", { name: "2. Mapea browser-invalid.csv" }),
  ).toBeVisible();
  await page.getByText("Metadatos y mapeo de roles", { exact: true }).click();
  await page
    .getByLabel("Nombre para guardar este perfil", { exact: true })
    .fill("Perfil navegador");
  await page
    .getByRole("button", { name: "Guardar perfil", exact: true })
    .click();
  await expect(
    page.getByText("Perfil guardado.", { exact: true }),
  ).toBeVisible();
  await page
    .getByLabel("Nombre para guardar este perfil", { exact: true })
    .fill("Perfil navegador actualizado");
  const saved = page.waitForResponse(
    (r) =>
      r.request().method() === "PUT" && r.url().includes("/import-profiles/"),
  );
  await page
    .getByRole("button", { name: "Guardar cambios del perfil", exact: true })
    .click();
  expect((await saved).status()).toBe(200);
  await page.getByRole("button", { name: "Analizar y normalizar" }).click();
  await expect(
    page.getByRole("checkbox", {
      name: "Seleccionar importación browser-invalid.csv",
    }),
  ).toBeChecked();
  await page
    .getByLabel("Instalación Moodle de destino", { exact: true })
    .selectOption(seed.connection_id);
  await page
    .getByRole("button", { name: "Validar operaciones", exact: true })
    .click();
  await expect(page).toHaveURL(/\/validations\//);
  await expect(
    page.getByRole("heading", { name: "Validación de operaciones" }),
  ).toBeVisible();
  await expect(
    page.locator(".process-banner").getByText("Completado", { exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page.getByRole("button", { name: "Configurar proceso", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("cell", { name: "Inválido", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Validación de operaciones" }),
  ).toBeVisible();
});

test("crear un borrador desde fixture validada, inspeccionar y cancelar sin escrituras", async ({
  page,
}) => {
  await login(page);
  await page.goto("/validations/" + seed.validation_id);
  await page
    .getByRole("button", { name: "Configurar proceso", exact: true })
    .click();
  await page
    .getByLabel("Nombre del proceso", { exact: true })
    .fill("Proceso navegador");
  await page
    .getByRole("button", { name: "Crear borrador", exact: true })
    .click();
  await expect(page).toHaveURL(/\/jobs\//);
  await expect(
    page.getByRole("heading", { name: "Proceso navegador", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Iniciar proceso", exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Cancelar", exact: true }).click();
  await expect(
    page.getByRole("dialog", { name: "Cancelar proceso", exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Confirmar", exact: true }).click();
  await expect(
    page.locator(".process-banner").getByText("Cancelado", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("cell", { name: "Omitida", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "Proceso navegador", exact: true }),
  ).toBeVisible();
});

test("conexión real persistida, token oculto y edición conservando credencial", async ({
  page,
}) => {
  await login(page);
  await page
    .getByRole("link", { name: "Conexiones Moodle", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Nueva conexión", exact: true })
    .click();
  await page
    .getByLabel("Nombre de la conexión", { exact: true })
    .fill("Destino creado en navegador");
  await page
    .getByLabel("URL base de Moodle", { exact: true })
    .fill("https://browser-target.invalid");
  await page
    .getByLabel("Token de servicios web", { exact: true })
    .fill("only-browser-test-token-never-real");
  await page
    .getByRole("button", { name: "Guardar conexión", exact: true })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Destino creado en navegador",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByText("only-browser-test-token-never-real"),
  ).toHaveCount(0);
  await page
    .getByRole("button", {
      name: "Editar Destino creado en navegador",
      exact: true,
    })
    .click();
  await expect(
    page.getByLabel("Nuevo token (opcional)", { exact: true }),
  ).toHaveValue("");
  await page
    .getByLabel("Descripción", { exact: true })
    .fill("Editado mediante navegador");
  await page
    .getByRole("button", { name: "Guardar conexión", exact: true })
    .click();
  await expect(
    page.getByText("Editado mediante navegador", { exact: true }),
  ).toBeVisible();
});

test("permisos de consulta y navegación móvil por teclado", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, seed.reader);
  await page.getByRole("button", { name: "Abrir menú", exact: true }).click();
  await expect(
    page.getByRole("link", { name: "Conexiones Moodle", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("link", { name: "Procesos", exact: true }).click();
  await expect(
    page.getByRole("heading", {
      name: "Procesos de matriculación",
      exact: true,
    }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth + 1,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/screens/mobile.png",
    fullPage: true,
  });
  await page.goto("/users");
  await expect(
    page.getByText("No tienes acceso a esta sección", { exact: true }),
  ).toBeVisible();
  const denied = await page.request.get("/api/v1/users");
  expect(denied.status()).toBe(403);
});

test("error de backend visible y navegación accesible del diálogo", async ({
  page,
}) => {
  await login(page);
  await page.route("**/api/v1/dashboard", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Servicio temporalmente no disponible" }),
    }),
  );
  await page.reload();
  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Servicio temporalmente no disponible" }),
  ).toBeVisible();
  await page.unroute("**/api/v1/dashboard");
  await page
    .getByRole("link", { name: "Conexiones Moodle", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Nueva conexión", exact: true })
    .click();
  await expect(
    page.getByRole("dialog", { name: "Nueva conexión Moodle", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
});
