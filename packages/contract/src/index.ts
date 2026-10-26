// The AMS <-> BI contract v0 (docs/ams-bi-contract-v0.md), as Zod schemas. A MIRROR of the AMS's packages/shared/src/collection.ts
// (BiCollectRequestSchema, BiSupplyBodySchema) and the pieces it uses (DataColumnSchema, BiQuerySchema). The AMS owns the contract:
// change it there first, then here. The test in this folder pins the example bodies of the contract document.
import { z } from 'zod';

export const EVIDENCE_TYPES = ['document', 'dataset'] as const;
export const SCHEDULE_EVERY = ['day', 'week', 'month', 'quarter', 'semester', 'year'] as const;
export const DATA_COLUMN_TYPES = ['text', 'number', 'integer', 'percent', 'date', 'choice', 'yes_no'] as const;

const NAME = /^[a-z][a-z0-9_]{0,63}$/;

export const DataColumnSchema = z.object({
  key: z.string().regex(/^[a-z][a-z0-9_]*$/),
  label: z.string().trim().min(1),
  type: z.enum(DATA_COLUMN_TYPES),
  unit: z.string().trim().min(1).nullable().optional(),
  required: z.boolean().default(false),
  choices: z.array(z.string().trim().min(1)).optional(),
  help: z.string().trim().min(1).optional(),
});
export type DataColumn = z.infer<typeof DataColumnSchema>;

export const BiFilterSchema = z.object({
  field: z.string().trim().regex(NAME),
  op: z.enum(['eq', 'ne', 'in', 'gt', 'gte', 'lt', 'lte']),
  value: z.union([z.string().max(200), z.number(), z.boolean(), z.array(z.union([z.string().max(200), z.number()])).max(100)]),
});

/** The body the AMS POSTs to the BI to ask for one period (contract 3.6). */
export const CollectRequestSchema = z.object({
  runId: z.string().min(1),
  /** The endpoint name the item asked for; absent for the default path. */
  endpoint: z.string().optional(),
  evidence: z.object({
    id: z.string(), title: z.string(), type: z.enum(EVIDENCE_TYPES), definition: z.string().nullable(),
    columns: z.array(DataColumnSchema).optional(),
  }),
  period: z.object({ label: z.string(), start: z.string(), end: z.string().nullable() }),
  /** The structured query, as data (never SQL); null when the item has none. */
  query: z.object({
    metric: z.string().trim().regex(NAME).optional(),
    dimensions: z.array(z.string().trim().regex(NAME)).max(20).optional(),
    filters: z.array(BiFilterSchema).max(20).optional(),
    grain: z.enum(SCHEDULE_EVERY).optional(),
  }).nullable(),
  callbackUrl: z.string().url(),
  callbackToken: z.string().min(1),
});
export type CollectRequest = z.infer<typeof CollectRequestSchema>;

const cell = z.union([z.string(), z.number(), z.boolean(), z.null()]);

/** What the BI sends back: in a 200 answer to the request, or in the callback (contract 4.2). Exactly one of rows, fileBase64, url. */
export const SupplyBodySchema = z.object({
  rows: z.array(z.record(z.string(), cell)).max(50_000).optional(),
  fileBase64: z.string().min(1).optional(),
  fileName: z.string().trim().min(1).max(200).optional(),
  mime: z.string().trim().min(1).max(200).optional(),
  url: z.url().optional(),
  asOf: z.string().trim().regex(/^\d{4}-\d{2}-\d{2}([T ].*)?$/),
  lineage: z.record(z.string(), z.unknown()).optional(),
  notes: z.string().trim().min(1).max(2000).optional(),
}).strict().superRefine((d, ctx) => {
  const n = (d.rows ? 1 : 0) + (d.fileBase64 ? 1 : 0) + (d.url ? 1 : 0);
  if (n !== 1) ctx.addIssue({ code: 'custom', path: [], message: 'send exactly one of rows, fileBase64 or url' });
  if (d.fileBase64 && !d.fileName) ctx.addIssue({ code: 'custom', path: ['fileName'], message: 'name the file' });
  if (d.url && !/^https:\/\//i.test(d.url)) ctx.addIssue({ code: 'custom', path: ['url'], message: 'the address must be https' });
});
export type SupplyBody = z.infer<typeof SupplyBodySchema>;

/** The AMS's answer to a callback (contract 4.2): 200 supplied, 401 token, 409 not waiting, 422 does not fit (fix and resend). */
export const SupplyIssuesSchema = z.object({ issues: z.array(z.object({ path: z.string(), message: z.string() })).optional() }).passthrough();
