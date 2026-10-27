// Evidence collection runs (TASK-090, DEC-031, docs/ams-bi-contract-v0.md 3.6 and 4). A run is one period of an evidence item's
// schedule: made by the scheduler job (or by a person, "Run now"), carried out by the item's collection method, and supplied by the
// evidence version that answers it. Pure shapes: the same definitions serve the API, the SPA, the worker and the BI contract.
import { z } from 'zod';
import { DataColumnSchema } from './dataset.js';
import { BiQuerySchema, EVIDENCE_METHODS, EVIDENCE_TYPES, SCHEDULE_EVERY } from './evidence.js';

export const COLLECTION_RUN_STATUSES = ['pending', 'requested', 'supplied', 'late', 'failed', 'skipped'] as const;
export type CollectionRunStatus = (typeof COLLECTION_RUN_STATUSES)[number];
/** Runs a person still has to do something about, or is waiting for. */
export const OPEN_RUN_STATUSES = ['pending', 'requested', 'late'] as const satisfies readonly CollectionRunStatus[];
export const COLLECTION_RUN_TRIGGERS = ['schedule', 'manual'] as const;

/** A BI call that fails is tried again by the scheduler this many times in all; then the run stays failed and the owner is told. */
export const MAX_COLLECTION_ATTEMPTS = 5;
/** Minutes to wait before the next attempt, after the 1st, 2nd, 3rd and 4th failure. */
export const COLLECTION_RETRY_MINUTES = [15, 60, 240, 720] as const;
/** Days the BI's callback token for a run stays valid. */
export const BI_CALLBACK_DAYS = 14;
/** Seconds the AMS waits for the BI's answer when the item says nothing. */
export const BI_DEFAULT_TIMEOUT_SECONDS = 60;
/** How long before the due time a run counts as "due soon" in the library filters. */
export const COLLECTION_DUE_SOON_DAYS = 7;

/** When the next attempt of a failed run is made, given how many attempts have failed so far; null = no more attempts. */
export function nextAttemptAfter(failedAttempts: number, now: Date): Date | null {
  if (failedAttempts >= MAX_COLLECTION_ATTEMPTS) return null;
  const minutes = COLLECTION_RETRY_MINUTES[Math.min(failedAttempts, COLLECTION_RETRY_MINUTES.length) - 1] ?? COLLECTION_RETRY_MINUTES[0];
  return new Date(now.getTime() + minutes * 60_000);
}

export const CollectionRunSchema = z.object({
  id: z.string(), evidenceItemId: z.string(), evidenceTitle: z.string(), evidenceType: z.enum(EVIDENCE_TYPES), method: z.enum(EVIDENCE_METHODS),
  ownerUserId: z.string().nullable(), ownerName: z.string().nullable(),
  periodLabel: z.string(),
  /** The first and last day of the period (yyyy-mm-dd); the end is null where the schedule does not say. */
  periodStart: z.string(), periodEnd: z.string().nullable(),
  /** The instant the evidence is due (end of the due day in the schedule's time zone), and that day as a person in that zone reads it (yyyy-mm-dd). */
  dueAt: z.string(), dueDate: z.string(),
  status: z.enum(COLLECTION_RUN_STATUSES), trigger: z.enum(COLLECTION_RUN_TRIGGERS),
  /** The evidence version that supplied it. */
  versionId: z.string().nullable(), versionNo: z.number().nullable(),
  requestedAt: z.string().nullable(), respondedAt: z.string().nullable(),
  attempts: z.number(), lastError: z.string().nullable(), skipReason: z.string().nullable(),
  /** When the scheduler tries a failed run again; null when it will not. */
  nextAttemptAt: z.string().nullable(),
  /** For a `request` run: the evidence request that was sent (a person answers it from their requests, or through its link). */
  requestId: z.string().nullable(), requestHasAccount: z.boolean().nullable(),
  createdAt: z.string(),
});
export type CollectionRun = z.infer<typeof CollectionRunSchema>;

export const CollectionRunsQuerySchema = z.object({
  /** One or more statuses, comma-separated. */
  status: z.string().optional(),
  itemId: z.uuid().optional(), ownerId: z.uuid().optional(),
  /** Only runs whose owner is the caller. */
  mine: z.enum(['true', 'false']).optional(),
  /** Only runs due before this instant (ISO). */
  dueBefore: z.string().optional(),
  limit: z.coerce.number().int().min(1).max(500).optional(),
});
export type CollectionRunsQuery = z.infer<typeof CollectionRunsQuerySchema>;

export const SkipRunSchema = z.object({ reason: z.string().trim().min(1, 'say why this period is skipped').max(1000) }).strict();
export type SkipRun = z.infer<typeof SkipRunSchema>;
export const SupplyRunSchema = z.object({ versionId: z.uuid() }).strict();
export type SupplyRun = z.infer<typeof SupplyRunSchema>;

/** What the server can say about the BI before a run is made (no secrets). */
export const CollectionConfigSchema = z.object({
  bi: z.object({
    configured: z.boolean(),
    /** The endpoint names the server resolves (`endpointKey` of a BI item); the default endpoint needs none. */
    endpointKeys: z.array(z.string()),
    /** Whether the address the BI calls back (APP_PUBLIC_URL) is known. */
    callbackConfigured: z.boolean(),
  }),
});
export type CollectionConfig = z.infer<typeof CollectionConfigSchema>;

// ---- The BI contract (docs/ams-bi-contract-v0.md 3.6, 4.2, 5) ---------------------------------------------------------------------

const asOf = z.string().trim().regex(/^\d{4}-\d{2}-\d{2}([T ].*)?$/, 'asOf is a date (yyyy-mm-dd) or a date and time');
const cell = z.union([z.string(), z.number(), z.boolean(), z.null()]);

/**
 * What the BI sends back, in the answer to the AMS's request (HTTP 200) and in its callback: rows (a dataset), a file (base64) or an
 * address, with the date the data is true as of and where it came from. Exactly one of the three.
 */
export const BiSupplyBodySchema = z.object({
  rows: z.array(z.record(z.string(), cell)).max(50_000).optional(),
  fileBase64: z.string().min(1).optional(),
  fileName: z.string().trim().min(1).max(200).optional(),
  mime: z.string().trim().min(1).max(200).optional(),
  url: z.url().optional(),
  asOf,
  lineage: z.record(z.string(), z.unknown()).optional(),
  notes: z.string().trim().min(1).max(2000).optional(),
}).strict().superRefine((d, ctx) => {
  const n = (d.rows ? 1 : 0) + (d.fileBase64 ? 1 : 0) + (d.url ? 1 : 0);
  if (n !== 1) ctx.addIssue({ code: 'custom', path: [], message: 'send exactly one of rows, fileBase64 or url' });
  if (d.fileBase64 && !d.fileName) ctx.addIssue({ code: 'custom', path: ['fileName'], message: 'name the file' });
  if (d.url && !/^https:\/\//i.test(d.url)) ctx.addIssue({ code: 'custom', path: ['url'], message: 'the address must be https' });
});
export type BiSupplyBody = z.infer<typeof BiSupplyBodySchema>;

/** The body the AMS POSTs to the BI to ask for one period (`{BI_BASE_URL}/ams/collect`). */
export const BiCollectRequestSchema = z.object({
  runId: z.string(),
  /** The endpoint name the item asked for (`endpointKey`); the BI may use it to route. Absent for the default. */
  endpoint: z.string().optional(),
  evidence: z.object({
    id: z.string(), title: z.string(), type: z.enum(EVIDENCE_TYPES), definition: z.string().nullable(),
    /** For a dataset: the columns the answer is checked against. */
    columns: z.array(DataColumnSchema).optional(),
  }),
  period: z.object({ label: z.string(), start: z.string(), end: z.string().nullable() }),
  /** The structured query, as data (never SQL); null when the item has none. */
  query: z.object({ metric: BiQuerySchema.shape.metric.optional(), dimensions: BiQuerySchema.shape.dimensions, filters: BiQuerySchema.shape.filters, grain: z.enum(SCHEDULE_EVERY).optional() }).nullable(),
  callbackUrl: z.string(),
  callbackToken: z.string(),
});
export type BiCollectRequest = z.infer<typeof BiCollectRequestSchema>;

/** The reason a collection run could not be carried out, worded for the run's error line. */
export const BI_NOT_CONFIGURED = 'The BI is not configured: set BI_BASE_URL (and BI_API_KEY) on the server.';
