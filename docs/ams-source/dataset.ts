// Dataset evidence (PRD 9.4): a specification (its columns and grain; what it means is the item's definition) and rows saved as versions.
// Cell parsing and validation live here so the grid in the browser and the service on the server agree exactly.
import { z } from 'zod';

export const DATA_COLUMN_TYPES = ['text', 'number', 'integer', 'percent', 'date', 'choice', 'yes_no'] as const;
export type DataColumnType = (typeof DATA_COLUMN_TYPES)[number];
export const DATA_COLUMN_TYPE_LABELS: Record<DataColumnType, string> = {
  text: 'Text', number: 'Number', integer: 'Whole number', percent: 'Percent', date: 'Date', choice: 'Choice', yes_no: 'Yes / No',
};
export const DATA_SOURCE_KINDS = ['manual_upload', 'governed_metric'] as const;

export const DataColumnSchema = z.object({
  key: z.string().regex(/^[a-z][a-z0-9_]*$/, 'a key is lower-case letters, digits and _'),
  label: z.string().trim().min(1, 'give the column a name'),
  type: z.enum(DATA_COLUMN_TYPES),
  unit: z.string().trim().min(1).nullable().optional(),
  required: z.boolean().default(false),
  choices: z.array(z.string().trim().min(1)).optional(),
  /** Shown under the question in the form. */
  help: z.string().trim().min(1).optional(),
}).superRefine((c, ctx) => {
  if (c.type === 'choice' && !c.choices?.length) ctx.addIssue({ code: 'custom', path: ['choices'], message: `list the choices for ${c.label}` });
});
export type DataColumn = z.infer<typeof DataColumnSchema>;

const uniqueKeys = (cols: DataColumn[]) => new Set(cols.map((c) => c.key)).size === cols.length;

export const DatasetSpecSchema = z.object({
  grain: z.string().nullable(), columns: z.array(DataColumnSchema),
  sourceKind: z.enum(DATA_SOURCE_KINDS), updatedAt: z.string().nullable(),
});
export type DatasetSpec = z.infer<typeof DatasetSpecSchema>;

export const SaveDatasetSpecSchema = z.object({
  grain: z.string().trim().min(1).nullable().optional(),
  columns: z.array(DataColumnSchema).min(1, 'add at least one column').refine(uniqueKeys, 'two columns have the same key'),
}).strict();
export type SaveDatasetSpec = z.input<typeof SaveDatasetSpecSchema>;

/** A stored cell: text, a number, true/false, or empty. Dates are ISO strings (yyyy-mm-dd). */
export type CellValue = string | number | boolean | null;
export type DataRow = Record<string, CellValue>;
const CellSchema = z.union([z.string(), z.number(), z.boolean(), z.null()]);

export const SaveDatasetRowsSchema = z.object({
  rows: z.array(z.record(z.string(), CellSchema)).max(50_000),
  notes: z.string().trim().min(1).optional(),
}).strict();
export type SaveDatasetRows = z.infer<typeof SaveDatasetRowsSchema>;

/** What a data version holds: the columns as they were when it was saved, and the rows. */
export const DatasetDataSchema = z.object({ columns: z.array(DataColumnSchema), rows: z.array(z.record(z.string(), CellSchema)) });
export type DatasetData = z.infer<typeof DatasetDataSchema>;

/** A key from a label: "Fall headcount (FTE)" → "fall_headcount_fte"; non-Latin labels fall back to col_N. */
export function keyFromLabel(label: string, taken: Iterable<string>, n: number): string {
  const base = label.normalize('NFKD').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '').replace(/^(\d)/, 'c_$1') || `col_${n}`;
  const used = new Set(taken);
  let key = base; let i = 2;
  while (used.has(key)) key = `${base}_${i++}`;
  return key;
}

/** Arabic-Indic and Persian digits → ASCII; Arabic decimal and thousands separators too. */
function asciiDigits(s: string): string {
  return s.replace(/[٠-٩]/g, (d) => String(d.charCodeAt(0) - 0x0660))
    .replace(/[۰-۹]/g, (d) => String(d.charCodeAt(0) - 0x06F0))
    .replace(/٫/g, '.').replace(/٬/g, ',');
}

const YES = new Set(['yes', 'y', 'true', '1', 'نعم']);
const NO = new Set(['no', 'n', 'false', '0', 'لا']);

/**
 * Reads what someone typed, pasted or imported into a cell of this column. Empty is null (an error only when the
 * column is required). Numbers accept thousands separators and Arabic digits; percents accept "45%" (stored as 45);
 * dates accept yyyy-mm-dd and d/m/yyyy.
 */
export function parseCell(col: Pick<DataColumn, 'type' | 'required' | 'choices' | 'label'>, raw: CellValue | undefined): { value: CellValue; error?: string } {
  if (raw === null || raw === undefined || (typeof raw === 'string' && raw.trim() === '')) {
    return col.required ? { value: null, error: `${col.label} is required` } : { value: null };
  }
  if (col.type === 'text') return { value: String(raw).normalize('NFC') };
  if (col.type === 'yes_no') {
    if (typeof raw === 'boolean') return { value: raw };
    const s = asciiDigits(String(raw)).trim().toLowerCase();
    if (YES.has(s)) return { value: true };
    if (NO.has(s)) return { value: false };
    return { value: String(raw), error: 'enter yes or no' };
  }
  if (col.type === 'choice') {
    const s = String(raw).trim().normalize('NFC');
    const hit = col.choices?.find((c) => c.normalize('NFC').toLowerCase() === s.toLowerCase());
    return hit ? { value: hit } : { value: s, error: `choose one of: ${(col.choices ?? []).join(', ')}` };
  }
  if (col.type === 'date') {
    const s = String(raw).trim();
    const iso = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(asciiDigits(s));
    const dmy = /^(\d{1,2})[/.](\d{1,2})[/.](\d{4})$/.exec(asciiDigits(s));
    const [y, m, d] = iso ? [+iso[1]!, +iso[2]!, +iso[3]!] : dmy ? [+dmy[3]!, +dmy[2]!, +dmy[1]!] : [0, 0, 0];
    const dt = new Date(Date.UTC(y, m - 1, d));
    if (y && dt.getUTCFullYear() === y && dt.getUTCMonth() === m - 1 && dt.getUTCDate() === d) return { value: dt.toISOString().slice(0, 10) };
    return { value: s, error: 'enter a date as yyyy-mm-dd' };
  }
  // number, integer, percent
  let n: number;
  if (typeof raw === 'number') n = raw;
  else if (typeof raw === 'boolean') return { value: String(raw), error: 'enter a number' };
  else {
    let s = asciiDigits(raw).trim().replace(/[\s\u00A0]/g, '');
    if (col.type === 'percent') s = s.replace(/%$/, '');
    s = /^-?\d{1,3}(,\d{3})+(\.\d+)?$/.test(s) ? s.replace(/,/g, '') : s;
    n = /^-?(\d+\.?\d*|\.\d+)$/.test(s) ? Number(s) : NaN;
  }
  if (!Number.isFinite(n)) return { value: String(raw), error: col.type === 'percent' ? 'enter a percent, e.g. 45 or 45%' : 'enter a number' };
  if (col.type === 'integer' && !Number.isInteger(n)) return { value: n, error: 'enter a whole number' };
  return { value: n };
}

export interface CellIssue { row: number; key: string; message: string }

/** Parses every cell of every row against the columns; unknown keys are dropped. Rows that are wholly empty are skipped. */
export function validateRows(columns: DataColumn[], rows: Record<string, CellValue | undefined>[]): { rows: DataRow[]; issues: CellIssue[] } {
  const out: DataRow[] = [];
  const issues: CellIssue[] = [];
  for (const raw of rows) {
    if (columns.every((c) => raw[c.key] === null || raw[c.key] === undefined || raw[c.key] === '')) continue;
    const row: DataRow = {};
    for (const c of columns) {
      const p = parseCell(c, raw[c.key]);
      row[c.key] = p.value;
      if (p.error) issues.push({ row: out.length, key: c.key, message: p.error });
    }
    out.push(row);
  }
  return { rows: out, issues };
}

/** How a stored value is shown in a cell and written to CSV. */
export function formatCell(col: Pick<DataColumn, 'type'>, v: CellValue | undefined): string {
  if (v === null || v === undefined) return '';
  if (col.type === 'yes_no' && typeof v === 'boolean') return v ? 'Yes' : 'No';
  return String(v);
}

// ---- Forms (DEC-020) ------------------------------------------------------------------------------------------------

/** The form of a dataset: whether it takes responses, its public link, and its responses waiting to be added. */
export const DataFormSchema = z.object({ open: z.boolean(), linkToken: z.string().nullable(), pending: z.number(), included: z.number() });
export type DataForm = z.infer<typeof DataFormSchema>;
export const SetFormOpenSchema = z.object({ open: z.boolean() }).strict();

/** What someone answering sees: the questions and what they are for, nothing else of the institution. */
export const PublicFormSchema = z.object({
  title: z.string(), definition: z.string().nullable(), institutionName: z.string(), columns: z.array(DataColumnSchema),
});
export type PublicForm = z.infer<typeof PublicFormSchema>;

export const SubmitResponseSchema = z.object({ answers: z.record(z.string(), CellSchema) }).strict();
export type SubmitResponse = z.infer<typeof SubmitResponseSchema>;

export const DataResponseSchema = z.object({
  id: z.string(), answers: z.record(z.string(), CellSchema), via: z.enum(['ams', 'link']), submittedByName: z.string().nullable(),
  createdAt: z.string(), includedInVersionNo: z.number().nullable(),
});
export type DataResponse = z.infer<typeof DataResponseSchema>;
