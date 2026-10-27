// Evidence (PRD 6.5, 9): items owned by the institution, versions that are never changed, links with a reason.
import { z } from 'zod';
import { DataColumnSchema } from './dataset.js';
import { NodePlansSchema } from './plans.js';
import { NodeChampionSchema, NodeScopeSchema } from './scope.js';

/** A document (a file people read) or a dataset (figures the system reads, with columns and a grain). Kinds within each come later as sub-types. */
export const EVIDENCE_TYPES = ['document', 'dataset'] as const;
export const CONFIDENTIALITY_LEVELS = ['public', 'internal', 'restricted'] as const;
const iso = z.string();

// ---- Collection method and schedule (DEC-031, TASK-089) --------------------------------------------------------------------------

/**
 * How an item is collected, ONE per item: `manual` (its owner uploads a file, registers a link or types the data), `form` (the
 * dataset's online form and spreadsheet template), `request` (ask a named person or an email address), `bi` (the BI supplies it)
 * and `survey` (reserved: accepted here, not selectable yet).
 */
export const EVIDENCE_METHODS = ['manual', 'form', 'request', 'bi', 'survey'] as const;
export type EvidenceMethod = (typeof EVIDENCE_METHODS)[number];
/** The methods a person can choose now; `survey` is shown as "coming". */
export const SELECTABLE_EVIDENCE_METHODS = ['manual', 'form', 'request', 'bi'] as const satisfies readonly EvidenceMethod[];
export const SCHEDULE_EVERY = ['day', 'week', 'month', 'quarter', 'semester', 'year'] as const;
export type ScheduleEvery = (typeof SCHEDULE_EVERY)[number];

const note = z.string().trim().min(1).max(2000);
const ManualConfigSchema = z.object({ instructions: note.optional(), expectedFormat: z.string().trim().min(1).max(200).optional() }).strict();
const FormConfigSchema = z.object({}).strict();
const RequestConfigSchema = z.object({
  assigneeUserId: z.uuid().optional(), assigneeEmail: z.string().trim().toLowerCase().pipe(z.email('enter an email address')).optional(), note: note.optional(),
}).strict().refine((c) => (c.assigneeUserId ? 1 : 0) + (c.assigneeEmail ? 1 : 0) === 1, { message: 'name one person or one email address to ask' });
/** A name such as `main` or `warehouse-1`, resolved from the server's environment: never an address someone types. */
export const BI_ENDPOINT_KEY = /^[A-Za-z][A-Za-z0-9_.-]{0,63}$/;
const NAME = /^[A-Za-z][A-Za-z0-9_.-]{0,99}$/;
/** What the BI is asked for: a metric and how to cut it, as data. Never SQL, never free text to run. */
export const BiQuerySchema = z.object({
  metric: z.string().trim().regex(NAME, 'a metric is a name such as enrollment_headcount'),
  dimensions: z.array(z.string().trim().regex(NAME, 'a dimension is a name such as program')).max(20).optional(),
  filters: z.array(z.object({
    field: z.string().trim().regex(NAME, 'a field is a name such as level'),
    op: z.enum(['eq', 'ne', 'in', 'gt', 'gte', 'lt', 'lte']),
    value: z.union([z.string().max(200), z.number(), z.boolean(), z.array(z.union([z.string().max(200), z.number()])).max(100)]),
  }).strict()).max(20).optional(),
}).strict();
export type BiQuery = z.infer<typeof BiQuerySchema>;
const BiConfigSchema = z.object({
  endpointKey: z.string().regex(BI_ENDPOINT_KEY, "an endpoint is a name from the server's settings, not an address").optional(),
  query: BiQuerySchema.optional(),
  /** The grain of the period asked for. */
  period: z.enum(SCHEDULE_EVERY).optional(),
  timeoutSeconds: z.number().int().min(1).max(600).optional(),
}).strict();
const SurveyConfigSchema = z.object({}).strict();
export const METHOD_CONFIG_SCHEMAS = {
  manual: ManualConfigSchema, form: FormConfigSchema, request: RequestConfigSchema, bi: BiConfigSchema, survey: SurveyConfigSchema,
} as const satisfies Record<EvidenceMethod, z.ZodType>;
export type MethodConfig = Record<string, unknown>;

/**
 * Checks a method's settings and the rule between method and type (the form is a dataset's), and returns the settings as stored.
 * Issues come in the usual `{ path, message }` shape, with paths under `methodConfig`.
 */
export function checkMethod(method: EvidenceMethod, type: (typeof EVIDENCE_TYPES)[number], config: unknown): { config: MethodConfig; issues: { path: string; message: string }[] } {
  const issues: { path: string; message: string }[] = [];
  if (method === 'form' && type !== 'dataset') issues.push({ path: 'method', message: 'the online form collects a dataset; choose another way to collect a document' });
  const r = METHOD_CONFIG_SCHEMAS[method].safeParse(config ?? {});
  if (!r.success) for (const i of r.error.issues) issues.push({ path: ['methodConfig', ...i.path].join('.'), message: i.message });
  return { config: r.success ? (r.data as MethodConfig) : {}, issues };
}

/** Whether a name is a time zone this runtime knows (IANA, such as `Asia/Dubai`). */
export const isTimeZone = (tz: string): boolean => {
  try { new Intl.DateTimeFormat('en', { timeZone: tz }); return true; } catch { return false; }
};
/** When an item is collected again: every day, week, month, quarter, semester (a term of the academic calendar) or year, from a start date. */
export const ScheduleSchema = z.object({
  every: z.enum(SCHEDULE_EVERY),
  startDate: z.iso.date(),
  /** Days after a period starts that the evidence is due. */
  dueAfterDays: z.number().int().min(0).max(3650),
  timezone: z.string().trim().min(1).refine(isTimeZone, 'unknown time zone'),
}).strict();
export type Schedule = z.infer<typeof ScheduleSchema>;

export const EvidenceVersionSchema = z.object({
  id: z.string(), versionNo: z.number(), fileName: z.string().nullable(), mime: z.string().nullable(), size: z.number().nullable(),
  sha256: z.string().nullable(), url: z.string().nullable(), asOfDate: z.string().nullable(), notes: z.string().nullable(), createdAt: iso,
  /** For a dataset: how many rows this version holds; null for files and links. */
  rowCount: z.number().nullable(),
});
export type EvidenceVersion = z.infer<typeof EvidenceVersionSchema>;

export const EvidenceItemSchema = z.object({
  id: z.string(), title: z.string(), definition: z.string().nullable(), type: z.enum(EVIDENCE_TYPES), subtype: z.string().nullable(),
  ownerUnitId: z.string().nullable(), ownerUserId: z.string().nullable(), ownerName: z.string().nullable(), periodLabel: z.string().nullable(),
  /** How it is collected (one per item), that method's settings, and the schedule (null = none). */
  method: z.enum(EVIDENCE_METHODS), methodConfig: z.record(z.string(), z.unknown()), schedule: ScheduleSchema.nullable(),
  /** When the next collection is due and when the last one ran; null while there is none. */
  nextDueAt: z.string().nullable(), lastRunAt: z.string().nullable(),
  /** A semester schedule the academic calendar cannot place ("no term defined"); null otherwise. Never guessed. */
  scheduleGap: z.enum(['no_term']).nullable(),
  confidentiality: z.enum(CONFIDENTIALITY_LEVELS), containsStudentData: z.boolean(), tags: z.array(z.string()),
  status: z.enum(['active', 'archived']), latest: EvidenceVersionSchema.nullable(), linkCount: z.number(),
  /** Links not yet approved or rejected. */
  proposedLinkCount: z.number(),
  /** Open requests to fill in this dataset's form. */
  openRequestCount: z.number(),
  /** For a dataset: whether its form takes responses, and responses not yet added to the data. */
  formOpen: z.boolean(), pendingResponses: z.number(),
  /** Collection runs of this item (TASK-090): those still open (pending, requested or late), the late ones and the failed ones. */
  runCounts: z.object({ open: z.number(), late: z.number(), failed: z.number() }).optional(),
});
export type EvidenceItem = z.infer<typeof EvidenceItemSchema>;

/**
 * What a link points at: a requirement of an engagement, an item of the institution's own framework, or a requirement of an
 * external standard linked directly at the library level (by code, so it carries across versions of the standard).
 * `frameworkLabel` names the standard for an external target (the accreditor's short name).
 */
export const LinkTargetSchema = z.object({
  kind: z.enum(['engagement', 'internal', 'external']), code: z.string(), title: z.string().nullable(),
  engagementRequirementId: z.string().nullable(), engagementId: z.string().nullable(), engagementTitle: z.string().nullable(),
  frameworkLabel: z.string().nullable().optional(),
});
export const EvidenceLinkSchema = z.object({
  id: z.string(), evidenceItemId: z.string(), evidenceTitle: z.string(), evidenceVersionId: z.string(), versionNo: z.number(),
  latestVersionNo: z.number(), newerVersionAvailable: z.boolean(), periodLabel: z.string().nullable(),
  /** The evidence is older than the review year allows (PRD 9.3); engagement links only. */
  stale: z.boolean(),
  target: LinkTargetSchema, rationale: z.string(), reviewStatus: z.enum(['proposed', 'approved', 'rejected']),
  /** Why it was rejected (required for a rejection) or the reviewer's note; with who decided and when, shown on the link everywhere. */
  reviewComment: z.string().nullable(), linkedBy: z.string().nullable(), linkedByName: z.string().nullable(), reviewedByName: z.string().nullable(),
  reviewedAt: iso.nullable(), createdAt: iso,
});
export type EvidenceLink = z.infer<typeof EvidenceLinkSchema>;

export const EvidenceDetailSchema = z.object({ item: EvidenceItemSchema, versions: z.array(EvidenceVersionSchema), links: z.array(EvidenceLinkSchema) });
export type EvidenceDetail = z.infer<typeof EvidenceDetailSchema>;

/** Evidence attached to an internal item that an external requirement is mapped to: offered, never linked by itself. */
export const EvidenceSuggestionSchema = z.object({
  evidenceItemId: z.string(), evidenceVersionId: z.string(), title: z.string(), versionNo: z.number(), periodLabel: z.string().nullable(),
  internalCode: z.string(), internalTitle: z.string().nullable(), relation: z.enum(['covers', 'partly_covers', 'related']), internalRationale: z.string(),
});
export type EvidenceSuggestion = z.infer<typeof EvidenceSuggestionSchema>;

/**
 * What a requirement of an external standard holds, for the hover card: the IQF items it is mapped to, the evidence those
 * items hold (inherited through approved mappings) and the evidence linked to the requirement itself. Short lists with the
 * full counts; one answer for the whole version, keyed by the requirement's code.
 */
export const RequirementContextEvidenceSchema = z.object({
  evidenceItemId: z.string(), title: z.string(), versionNo: z.number(), periodLabel: z.string().nullable(),
});
export const RequirementContextSchema = z.object({
  mappings: z.array(z.object({
    id: z.string(), internalCode: z.string(), internalTitle: z.string().nullable(), relation: z.enum(['covers', 'partly_covers', 'related']),
    reviewStatus: z.enum(['pending', 'approved', 'rejected']),
  })),
  inherited: z.array(RequirementContextEvidenceSchema.extend({ internalCode: z.string() })),
  inheritedCount: z.number(),
  direct: z.array(RequirementContextEvidenceSchema.extend({ reviewStatus: z.enum(['proposed', 'approved', 'rejected']) })),
  directCount: z.number(),
  /** What the requirement is assigned to and who answers for it, with where each comes from (TASK-086). Same answer, so the hover card needs no second request. */
  scope: NodeScopeSchema.optional(),
  champion: NodeChampionSchema.optional(),
  /** The cycle plans in effect on the requirement, with where each comes from (TASK-081). */
  plans: NodePlansSchema.optional(),
});
export type RequirementContext = z.infer<typeof RequirementContextSchema>;
export const RequirementContextsSchema = z.object({ byCode: z.record(z.string(), RequirementContextSchema) });
export type RequirementContexts = z.infer<typeof RequirementContextsSchema>;

const methodRules = (d: { type?: (typeof EVIDENCE_TYPES)[number] | undefined; method?: EvidenceMethod | undefined; methodConfig?: unknown }, ctx: z.RefinementCtx, fallbackType?: (typeof EVIDENCE_TYPES)[number]) => {
  const type = d.type ?? fallbackType;
  if (!d.method || !type) return;
  for (const i of checkMethod(d.method, type, d.methodConfig).issues) ctx.addIssue({ code: 'custom', path: i.path.split('.'), message: i.message });
};

export const CreateEvidenceSchema = z.object({
  title: z.string().trim().min(1), definition: z.string().trim().optional(), type: z.enum(EVIDENCE_TYPES), subtype: z.string().trim().min(1).optional(),
  ownerUnitId: z.uuid().optional(), ownerUserId: z.uuid().optional(), periodLabel: z.string().trim().min(1).optional(),
  confidentiality: z.enum(CONFIDENTIALITY_LEVELS).default('internal'), containsStudentData: z.boolean().default(false),
  tags: z.array(z.string().trim().min(1)).default([]),
  /** The collection method (default `manual`) and its settings; the schedule is optional. */
  method: z.enum(EVIDENCE_METHODS).default('manual'), methodConfig: z.record(z.string(), z.unknown()).default({}), schedule: ScheduleSchema.nullable().optional(),
  /** For a link to a document kept elsewhere (e.g. SharePoint): registers version 1 with this address. */
  url: z.url().optional(),
}).strict().superRefine((d, ctx) => methodRules(d, ctx));
export type CreateEvidence = z.input<typeof CreateEvidenceSchema>;

export const UpdateEvidenceSchema = z.object({
  title: z.string().trim().min(1).optional(), definition: z.string().trim().nullable().optional(),
  /** A document becomes a dataset (or back) only while it holds no versions of the other kind. */
  type: z.enum(EVIDENCE_TYPES).optional(),
  ownerUnitId: z.uuid().nullable().optional(), ownerUserId: z.uuid().nullable().optional(), periodLabel: z.string().trim().nullable().optional(),
  confidentiality: z.enum(CONFIDENTIALITY_LEVELS).optional(), containsStudentData: z.boolean().optional(),
  tags: z.array(z.string().trim().min(1)).optional(), status: z.enum(['active', 'archived']).optional(),
  /** Changing the method without settings resets them; settings alone are checked against the item's current method by the service. */
  method: z.enum(EVIDENCE_METHODS).optional(), methodConfig: z.record(z.string(), z.unknown()).optional(), schedule: ScheduleSchema.nullable().optional(),
}).strict().superRefine((d, ctx) => { if (d.method && d.methodConfig) methodRules(d, ctx, 'dataset'); });
export type UpdateEvidence = z.infer<typeof UpdateEvidenceSchema>;

export const LinkEvidenceSchema = z.object({ evidenceVersionId: z.uuid(), rationale: z.string().trim().min(1, 'say why this evidence supports it') }).strict();
export type LinkEvidence = z.infer<typeof LinkEvidenceSchema>;
/** A rejection says why (the proposer is told); an approval may carry a note. */
export const ReviewLinkSchema = z.object({ decision: z.enum(['approved', 'rejected']), comment: z.string().trim().min(1).optional() }).strict()
  .refine((v) => v.decision !== 'rejected' || !!v.comment, { message: 'say why it is rejected', path: ['comment'] });
export type ReviewLink = z.infer<typeof ReviewLinkSchema>;
/** The proposer answers a rejection: the link goes back to review with a new reason. */
export const ResubmitLinkSchema = z.object({ rationale: z.string().trim().min(1, 'say why this evidence supports it') }).strict();
export type ResubmitLink = z.infer<typeof ResubmitLinkSchema>;

/** The year a period label starts in ("AY2025-26" → 2025, "2024" → 2024), or null when it names none. */
export const periodYear = (label: string | null | undefined): number | null => {
  const m = /(19|20)\d{2}/.exec(label ?? '');
  return m ? Number(m[0]) : null;
};
/** PRD 9.3: evidence is stale for an engagement when its period starts before the review year minus this many years. */
export const STALE_AFTER_YEARS = 3;

// ---- Requests (DEC-018) --------------------------------------------------------------------------------------------

export const EVIDENCE_REQUEST_STATUSES = ['open', 'supplied', 'cancelled'] as const;
/** Days a one-time response link stays valid. */
export const REQUEST_LINK_DAYS = 30;

export const EvidenceRequestSchema = z.object({
  id: z.string(), internalCode: z.string().nullable(), internalTitle: z.string().nullable(),
  /** A form request: the dataset whose form is to be filled in (else a file is asked for). */
  dataItemId: z.string().nullable(), dataItemTitle: z.string().nullable(), title: z.string(), message: z.string().nullable(),
  assigneeEmail: z.string(), assigneeName: z.string().nullable(), assigneeHasAccount: z.boolean(), dueDate: z.string().nullable(),
  status: z.enum(EVIDENCE_REQUEST_STATUSES), overdue: z.boolean(), requestedByName: z.string().nullable(), createdAt: z.string(),
  suppliedAt: z.string().nullable(), suppliedNote: z.string().nullable(), linkExpiresAt: z.string().nullable(),
  evidenceItemId: z.string().nullable(),
});
export type EvidenceRequest = z.infer<typeof EvidenceRequestSchema>;

/** What a new request (or a new link for one) returns: the one-time link secret is shown once and never stored. */
export const IssuedRequestSchema = z.object({ request: EvidenceRequestSchema, linkToken: z.string().nullable() });
export type IssuedRequest = z.infer<typeof IssuedRequestSchema>;

export const CreateEvidenceRequestSchema = z.object({
  title: z.string().trim().min(1, 'say what is needed'),
  assigneeEmail: z.email('enter an email address').trim().toLowerCase(),
  message: z.string().trim().min(1).optional(),
  dueDate: z.iso.date().optional(),
}).strict();
export type CreateEvidenceRequest = z.infer<typeof CreateEvidenceRequestSchema>;

/** Ask one or more people to fill in a dataset's form; each gets their own request. */
export const CreateFormRequestSchema = z.object({
  assigneeEmails: z.array(z.email('enter email addresses').trim().toLowerCase()).min(1, 'enter at least one email address').max(50),
  message: z.string().trim().min(1).optional(),
  dueDate: z.iso.date().optional(),
}).strict();
export type CreateFormRequest = z.infer<typeof CreateFormRequestSchema>;

/** What the one-time link page shows: only this request, and for a form request the form's questions. */
export const RequestByLinkSchema = z.object({
  title: z.string(), message: z.string().nullable(), dueDate: z.string().nullable(), internalCode: z.string().nullable(), internalTitle: z.string().nullable(),
  requestedByName: z.string().nullable(), institutionName: z.string(),
  form: z.object({ definition: z.string().nullable(), columns: z.array(DataColumnSchema) }).nullable(),
});
export type RequestByLink = z.infer<typeof RequestByLinkSchema>;
