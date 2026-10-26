import { describe, expect, it } from 'vitest';
import { CollectRequestSchema, SupplyBodySchema } from './index.js';

// The example bodies of docs/ams-bi-contract-v0.md 3.6 and 4.2.
const request = {
  runId: '0b6c5d2e-0000-4000-8000-000000000001',
  endpoint: 'warehouse',
  evidence: {
    id: '0b6c5d2e-0000-4000-8000-000000000002', title: 'Enrollment headcount', type: 'dataset', definition: 'Students enrolled per program',
    columns: [{ key: 'program', label: 'Program', type: 'text', required: true }, { key: 'n', label: 'Headcount', type: 'integer', required: true }],
  },
  period: { label: 'Fall 2026', start: '2026-08-24', end: '2026-12-18' },
  query: { metric: 'enrollment_headcount', dimensions: ['program'], filters: [{ field: 'level', op: 'eq', value: 'bachelor' }], grain: 'semester' },
  callbackUrl: 'https://ams.example.org/api/bi/v0/runs/0b6c5d2e-0000-4000-8000-000000000001/supply',
  callbackToken: 'x'.repeat(43),
};

describe('the contract v0', () => {
  it('reads the request of 3.6', () => {
    expect(CollectRequestSchema.parse(request).evidence.columns?.[1]?.type).toBe('integer');
    expect(CollectRequestSchema.safeParse({ ...request, query: null, endpoint: undefined }).success).toBe(true);
  });

  it('builds the supply of 4.2: exactly one of rows, a file or an https address', () => {
    expect(SupplyBodySchema.safeParse({ rows: [{ program: 'BSME', n: 120 }], asOf: '2026-10-20', lineage: { steward: 'registrar' } }).success).toBe(true);
    expect(SupplyBodySchema.safeParse({ asOf: '2026-10-20' }).success).toBe(false);
    expect(SupplyBodySchema.safeParse({ url: 'http://x.example.org/a.pdf', asOf: '2026-10-20' }).success).toBe(false);
    expect(SupplyBodySchema.safeParse({ fileBase64: 'AA==', asOf: '2026-10-20' }).success).toBe(false);
    expect(SupplyBodySchema.safeParse({ rows: [], asOf: '20 Oct' }).success).toBe(false);
  });
});
