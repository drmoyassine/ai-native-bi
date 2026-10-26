import { z } from 'zod';

const EnvSchema = z.object({
  NODE_ENV: z.string().default('development'),
  PORT: z.coerce.number().int().positive().default(4000),
  DATABASE_URL: z.string().min(1),
  /** A superuser address on the same server; when set, the BI creates its role and database (co-deployment, AMS DEC-034). */
  BI_DATABASE_ADMIN_URL: z.string().min(1).optional(),
  /** The key the AMS sends as a bearer credential (the AMS's BI_API_KEY). */
  BI_API_KEY: z.string().min(16, 'BI_API_KEY must be at least 16 characters'),
  /** The only origin the BI calls back (the AMS's APP_PUBLIC_URL). */
  AMS_CALLBACK_ORIGIN: z.string().url().transform((u) => new URL(u).origin),
  CALLBACK_TIMEOUT_MS: z.coerce.number().int().positive().default(30_000),
});
export type Env = z.infer<typeof EnvSchema>;

/** Reads the environment; an empty value (as in a copied .env.example) means "not set". */
export function loadEnv(source: NodeJS.ProcessEnv = process.env): Env {
  const clean = Object.fromEntries(Object.entries(source).filter(([, v]) => v !== undefined && v !== ''));
  return EnvSchema.parse(clean);
}
