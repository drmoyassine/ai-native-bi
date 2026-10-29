import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { api, type CalendarSummary, type Me } from './api';
import { Button } from './components/ui/button';
import { Card } from './components/ui/card';
import { Input } from './components/ui/input';
import { useTranslation } from './i18n';
import { PRIMARY_LANGUAGE } from './languages';

// The Model page (docs/data-model-spec.md § 6, M3): what the organization reports on, as subjects, entities and events. A change is a
// draft until an admin or the subject's steward approves it, after seeing what it changes. Nothing here names a domain (DEC-037).

type Kind = 'subject' | 'entity' | 'event';
type Words = Record<string, string>;
type Expects = 'key' | 'date' | 'text' | 'number';

interface Part {
  name: string;
  needed?: boolean;
  expects?: Expects;
  personal?: boolean;
  label?: Words;
  description?: Words;
  aliases?: string[];
  normalize?: 'lower' | null;
}

type Rule =
  | { type: 'group'; part: string; groups: Record<string, string>; otherwise?: string | null }
  | { type: 'join'; parts: string[]; separator?: string }
  | { type: 'date_part'; part: string; unit: 'year' | 'quarter' | 'month' | 'week' | 'day_of_week' }
  | { type: 'period'; part: string; calendar: string }
  | { type: 'arithmetic'; left: string | number; op: '+' | '-' | '*' | '/'; right: string | number }
  | { type: 'bucket'; part: string; edges: number[]; labels: string[] }
  | { type: 'first_of'; parts: string[] };

interface Derived {
  name: string;
  label?: Words;
  rule: Rule;
}

interface Body {
  subject?: string;
  label: Words;
  description?: Words;
  steward?: string | null;
  parts?: Part[];
  grain?: string[];
  snapshot_by?: string[];
  derived?: Derived[];
  key?: string;
  personal?: boolean;
  attributes?: Part[];
}

interface Version {
  version: number;
  status: string;
  body: Body;
  template: string | null;
}

interface Definition {
  kind: Kind;
  name: string;
  current: Version | null;
  draft: Version | null;
}

interface Changes {
  new: boolean;
  changes: string[];
  warnings: string[];
}

const NAME = '^[a-z][a-z0-9_]{0,62}$';
const RULES: Rule['type'][] = ['group', 'join', 'date_part', 'period', 'arithmetic', 'bucket', 'first_of'];

function words(w: Words | undefined, locale: string): string {
  return (w && (w[locale] || w[PRIMARY_LANGUAGE])) || '';
}

function newRule(type: Rule['type'], parts: Part[], calendars: CalendarSummary[]): Rule {
  const first = parts[0]?.name ?? '';
  switch (type) {
    case 'group':
      return { type, part: first, groups: { '': '' } };
    case 'join':
      return { type, parts: parts.slice(0, 2).map((p) => p.name), separator: ' ' };
    case 'date_part':
      return { type, part: parts.find((p) => p.expects === 'date')?.name ?? first, unit: 'year' };
    case 'period':
      return { type, part: parts.find((p) => p.expects === 'date')?.name ?? first, calendar: calendars[0]?.name ?? '' };
    case 'arithmetic':
      return { type, left: parts.find((p) => p.expects === 'number')?.name ?? first, op: '+', right: 0 };
    case 'bucket':
      return { type, part: parts.find((p) => p.expects === 'number')?.name ?? first, edges: [10], labels: ['', ''] };
    default:
      return { type: 'first_of', parts: parts.slice(0, 2).map((p) => p.name) };
  }
}

export function Model({ me }: { me: Me }) {
  const { t } = useTranslation();
  const [defs, setDefs] = useState<Definition[] | null>(null);
  const [open, setOpen] = useState<{ kind: Kind; name: string | null; subject?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setDefs((await api.get<{ definitions: Definition[] }>('/model')).definitions);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  if (!defs) return <p className="text-muted-foreground">{error ?? t('loading')}</p>;
  const locale = me.locale;
  const subjects = defs.filter((d) => d.kind === 'subject');
  const bodyOf = (d: Definition) => (d.draft ?? d.current)!.body;
  const under = (subject: string, kind: Kind) => defs.filter((d) => d.kind === kind && bodyOf(d).subject === subject);

  if (open) {
    const found = open.name ? defs.find((d) => d.kind === open.kind && d.name === open.name) : undefined;
    return (
      <Editor
        me={me}
        kind={open.kind}
        definition={found}
        subjects={subjects}
        subject={open.subject}
        onClose={() => {
          setOpen(null);
          void load();
        }}
      />
    );
  }

  return (
    <section className="max-w-5xl">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-3">
        <h1 className="m-0">{t('model.title')}</h1>
        <Button onClick={() => setOpen({ kind: 'subject', name: null })}>{t('model.newSubject')}</Button>
      </div>
      <p className="text-sm text-muted-foreground">{t('model.intro')}</p>
      {subjects.length === 0 && <Card className="mt-4 text-center text-muted-foreground">{t('model.empty')}</Card>}
      {subjects.map((s) => (
        <Card key={s.name} className="mt-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <button type="button" className="link text-lg font-semibold" onClick={() => setOpen({ kind: 'subject', name: s.name })}>
                {words(bodyOf(s).label, locale) || s.name}
              </button>{' '}
              <Status d={s} />
              {bodyOf(s).steward && (
                <span className="ms-2 text-sm text-muted-foreground">{t('model.stewardIs', { email: bodyOf(s).steward })}</span>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setOpen({ kind: 'event', name: null, subject: s.name })}>
                {t('model.newEvent')}
              </Button>
              <Button variant="outline" onClick={() => setOpen({ kind: 'entity', name: null, subject: s.name })}>
                {t('model.newEntity')}
              </Button>
            </div>
          </div>
          {(['event', 'entity'] as const).map((kind) =>
            under(s.name, kind).length ? (
              <div key={kind} className="mt-3">
                <h3 className="m-0 text-sm text-muted-foreground">{t(kind === 'event' ? 'model.events' : 'model.entities')}</h3>
                <ul className="m-0 list-none p-0">
                  {under(s.name, kind).map((d) => (
                    <li key={d.name} className="flex flex-wrap items-baseline gap-2 py-1">
                      <button type="button" className="link" onClick={() => setOpen({ kind, name: d.name })}>
                        {words(bodyOf(d).label, locale) || d.name}
                      </button>
                      <code className="text-xs">{d.name}</code>
                      <Status d={d} />
                      {kind === 'event' && (
                        <span className="text-xs text-muted-foreground">
                          {t('model.partsCount', { parts: bodyOf(d).parts?.length ?? 0, derived: bodyOf(d).derived?.length ?? 0 })}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null,
          )}
        </Card>
      ))}
    </section>
  );
}

function Status({ d }: { d: Definition }) {
  const { t } = useTranslation();
  return (
    <>
      {d.current && <span className="badge live">{t('model.version', { version: d.current.version })}</span>}{' '}
      {d.draft && <span className="badge draft">{t('model.draftWaiting')}</span>}{' '}
      {d.current?.template && (
        <span className="text-xs text-muted-foreground">{t('model.fromTemplate', { template: d.current.template })}</span>
      )}
    </>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block text-sm">
      {label}
      {children}
      {hint && <span className="mt-1 block text-muted-foreground">{hint}</span>}
    </label>
  );
}

export function WordsInput({ value, onChange, me, label }: { value: Words; onChange: (w: Words) => void; me: Me; label: string }) {
  const secondary = me.organization.secondary_language;
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <Field label={`${label} (English)`}>
        <Input value={value.en ?? ''} onChange={(e) => onChange({ ...value, en: e.target.value })} />
      </Field>
      {secondary && (
        <Field label={`${label} (${secondary})`}>
          <Input
            dir="auto"
            lang={secondary}
            value={value[secondary] ?? ''}
            onChange={(e) => onChange({ ...value, [secondary]: e.target.value })}
          />
        </Field>
      )}
    </div>
  );
}

function Editor({
  me,
  kind,
  definition,
  subjects,
  subject,
  onClose,
}: {
  me: Me;
  kind: Kind;
  definition?: Definition;
  subjects: Definition[];
  subject?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const start = (definition?.draft ?? definition?.current)?.body;
  const [name, setName] = useState(definition?.name ?? '');
  const [body, setBody] = useState<Body>(
    start ??
      (kind === 'subject'
        ? { label: {} }
        : kind === 'event'
          ? { subject, label: {}, parts: [{ name: '', expects: 'text', label: {} }], grain: [], snapshot_by: [], derived: [] }
          : { subject, label: {}, key: '', attributes: [{ name: '', expects: 'key', label: {} }] }),
  );
  const [changes, setChanges] = useState<Changes | null>(null);
  const [hasDraft, setHasDraft] = useState(Boolean(definition?.draft));
  const [people, setPeople] = useState<{ name: string; email: string }[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (kind === 'subject')
      void api
        .get<{ people: { name: string; email: string }[] }>('/model/stewards')
        .then((r) => setPeople(r.people))
        .catch(() => undefined);
  }, [kind]);

  const preview = useCallback(async () => {
    if (!definition?.name && !name) return;
    try {
      setChanges(await api.get<Changes>(`/model/${kind}/${definition?.name ?? name}/changes`));
    } catch {
      setChanges(null);
    }
  }, [kind, definition?.name, name]);
  useEffect(() => {
    if (hasDraft) void preview();
  }, [hasDraft, preview]);

  const set = (change: Partial<Body>) => setBody((b) => ({ ...b, ...change }));
  const parts = body.parts ?? [];
  const partNames = parts.map((p) => p.name).filter(Boolean);

  async function saveDraft() {
    setError(null);
    setNotice(null);
    try {
      const clean: Body = { ...body };
      if (kind === 'event') {
        clean.parts = parts.filter((p) => p.name);
        clean.grain = (body.grain ?? []).filter((g) => partNames.includes(g));
        clean.snapshot_by = (body.snapshot_by ?? []).filter((g) => partNames.includes(g));
      }
      if (kind === 'entity') clean.attributes = (body.attributes ?? []).filter((p) => p.name);
      if (kind === 'subject' && !clean.steward) delete clean.steward;
      await api.put(`/model/${kind}/${name}`, clean);
      setHasDraft(true);
      setNotice(t('model.draftSaved'));
      await preview();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  async function approve() {
    setError(null);
    try {
      await api.post(`/model/${kind}/${name}/approve`);
      onClose();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="max-w-5xl">
      <button className="link" onClick={onClose}>
        ← {t('model.title')}
      </button>
      <h1>{definition ? words(start?.label, me.locale) || definition.name : t(`model.new_${kind}`)}</h1>
      <Card className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label={t('model.name')} hint={t('model.nameHint')}>
            <Input value={name} disabled={Boolean(definition)} pattern={NAME} required onChange={(e) => setName(e.target.value)} />
          </Field>
          {kind !== 'subject' && (
            <Field label={t('model.subject')}>
              <select className="mt-1 block w-full" value={body.subject ?? ''} onChange={(e) => set({ subject: e.target.value })}>
                {subjects.map((s) => (
                  <option key={s.name} value={s.name}>
                    {words((s.current ?? s.draft)!.body.label, me.locale) || s.name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {kind === 'subject' && (
            <Field label={t('model.steward')} hint={t('model.stewardHint')}>
              <select className="mt-1 block w-full" value={body.steward ?? ''} onChange={(e) => set({ steward: e.target.value || null })}>
                <option value="">{t('model.noSteward')}</option>
                {people.map((p) => (
                  <option key={p.email} value={p.email}>
                    {p.name} ({p.email})
                  </option>
                ))}
              </select>
            </Field>
          )}
        </div>
        <WordsInput me={me} label={t('model.label')} value={body.label} onChange={(label) => set({ label })} />
        <WordsInput
          me={me}
          label={t('model.description')}
          value={body.description ?? {}}
          onChange={(description) => set({ description })}
        />

        {kind === 'event' && (
          <>
            <PartsTable
              me={me}
              parts={parts}
              onChange={(p) => set({ parts: p })}
              grain={body.grain ?? []}
              snapshot={body.snapshot_by ?? []}
              onGrain={(grain) => set({ grain })}
              onSnapshot={(snapshot_by) => set({ snapshot_by })}
            />
            <DerivedList me={me} parts={parts} derived={body.derived ?? []} onChange={(derived) => set({ derived })} />
          </>
        )}
        {kind === 'entity' && (
          <>
            <PartsTable me={me} parts={body.attributes ?? []} onChange={(attributes) => set({ attributes })} />
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label={t('model.key')}>
                <select className="mt-1 block w-full" value={body.key ?? ''} onChange={(e) => set({ key: e.target.value })}>
                  <option value="" />
                  {(body.attributes ?? [])
                    .filter((a) => a.name)
                    .map((a) => (
                      <option key={a.name} value={a.name}>
                        {a.name}
                      </option>
                    ))}
                </select>
              </Field>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={Boolean(body.personal)} onChange={(e) => set({ personal: e.target.checked })} />
                {t('model.personalEntity')}
              </label>
            </div>
          </>
        )}

        {error && <p className="text-sm text-[var(--error)]">{error}</p>}
        {notice && <p className="text-sm text-[var(--ok)]">{notice}</p>}
        <div className="flex flex-wrap gap-2">
          <Button onClick={() => void saveDraft()} disabled={!new RegExp(NAME).test(name)}>
            {t('model.saveDraft')}
          </Button>
        </div>
      </Card>

      {hasDraft && changes && (
        <Card className="mt-4">
          <h2 className="mt-0">{t('model.whatChanges')}</h2>
          {changes.new && <p className="text-sm">{t('model.isNew')}</p>}
          {changes.changes.length > 0 && (
            <ul>
              {changes.changes.map((c) => (
                <li key={c}>{c}</li>
              ))}
            </ul>
          )}
          {changes.warnings.map((w) => (
            <p key={w} className="text-sm text-[var(--warn)]">
              {w}
            </p>
          ))}
          <p className="text-sm text-muted-foreground">{t('model.approveHint')}</p>
          <Button onClick={() => void approve()}>{t('model.approve')}</Button>
        </Card>
      )}
    </section>
  );
}

function PartsTable({
  me,
  parts,
  onChange,
  grain,
  snapshot,
  onGrain,
  onSnapshot,
}: {
  me: Me;
  parts: Part[];
  onChange: (p: Part[]) => void;
  grain?: string[];
  snapshot?: string[];
  onGrain?: (g: string[]) => void;
  onSnapshot?: (g: string[]) => void;
}) {
  const { t } = useTranslation();
  const set = (i: number, change: Partial<Part>) => onChange(parts.map((p, j) => (j === i ? { ...p, ...change } : p)));
  const toggle = (list: string[], name: string, on: boolean) => (on ? [...list, name] : list.filter((x) => x !== name));
  return (
    <div>
      <h3>{t('model.parts')}</h3>
      <p className="text-sm text-muted-foreground">{t('model.partsHint')}</p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t('model.name')}</th>
              <th>{t('model.label')}</th>
              <th>{t('model.kind')}</th>
              <th>{t('model.needed')}</th>
              <th>{t('model.personal')}</th>
              <th>{t('model.aliases')}</th>
              {onGrain && <th title={t('model.grainHint')}>{t('model.grain')}</th>}
              {onSnapshot && <th title={t('model.snapshotHint')}>{t('model.snapshot')}</th>}
              <th />
            </tr>
          </thead>
          <tbody>
            {parts.map((p, i) => (
              <tr key={i}>
                <td>
                  <Input aria-label={t('model.name')} value={p.name} pattern={NAME} onChange={(e) => set(i, { name: e.target.value })} />
                </td>
                <td>
                  <Input
                    aria-label={t('model.label')}
                    value={words(p.label, me.locale)}
                    onChange={(e) => set(i, { label: { ...p.label, en: e.target.value } })}
                  />
                </td>
                <td>
                  <select value={p.expects ?? 'text'} onChange={(e) => set(i, { expects: e.target.value as Expects })}>
                    {(['key', 'text', 'date', 'number'] as const).map((k) => (
                      <option key={k} value={k}>
                        {t(`model.kind_${k}`)}
                      </option>
                    ))}
                  </select>
                </td>
                <td>
                  <input type="checkbox" checked={Boolean(p.needed)} onChange={(e) => set(i, { needed: e.target.checked })} />
                </td>
                <td>
                  <input type="checkbox" checked={Boolean(p.personal)} onChange={(e) => set(i, { personal: e.target.checked })} />
                </td>
                <td>
                  <Input
                    aria-label={t('model.aliases')}
                    value={(p.aliases ?? []).join(', ')}
                    onChange={(e) =>
                      set(i, {
                        aliases: e.target.value
                          .split(',')
                          .map((a) => a.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </td>
                {onGrain && (
                  <td>
                    <input
                      type="checkbox"
                      checked={grain!.includes(p.name)}
                      onChange={(e) => onGrain(toggle(grain!, p.name, e.target.checked))}
                    />
                  </td>
                )}
                {onSnapshot && (
                  <td>
                    <input
                      type="checkbox"
                      checked={snapshot!.includes(p.name)}
                      onChange={(e) => onSnapshot(toggle(snapshot!, p.name, e.target.checked))}
                    />
                  </td>
                )}
                <td>
                  <button type="button" className="link" onClick={() => onChange(parts.filter((_, j) => j !== i))}>
                    {t('model.remove')}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button type="button" className="link" onClick={() => onChange([...parts, { name: '', expects: 'text', label: {} }])}>
        + {t('model.addPart')}
      </button>
    </div>
  );
}

function DerivedList({ me, parts, derived, onChange }: { me: Me; parts: Part[]; derived: Derived[]; onChange: (d: Derived[]) => void }) {
  const { t } = useTranslation();
  const [calendars, setCalendars] = useState<CalendarSummary[]>([]);
  useEffect(() => {
    api
      .get<{ calendars: CalendarSummary[] }>('/calendars')
      .then((r) => setCalendars(r.calendars))
      .catch(() => setCalendars([]));
  }, []);
  const named = parts.filter((p) => p.name);
  const set = (i: number, change: Partial<Derived>) => onChange(derived.map((d, j) => (j === i ? { ...d, ...change } : d)));
  const partSelect = (value: string, onPick: (v: string) => void, only?: Expects) => (
    <select value={value} onChange={(e) => onPick(e.target.value)}>
      {named
        .filter((p) => !only || p.expects === only)
        .map((p) => (
          <option key={p.name} value={p.name}>
            {p.name}
          </option>
        ))}
    </select>
  );
  return (
    <div>
      <h3>{t('model.derived')}</h3>
      <p className="text-sm text-muted-foreground">{t('model.derivedHint')}</p>
      {derived.map((d, i) => {
        const r = d.rule;
        const setRule = (rule: Rule) => set(i, { rule });
        return (
          <div key={i} className="card mt-2 space-y-2">
            <div className="flex flex-wrap items-end gap-3">
              <Field label={t('model.name')}>
                <Input value={d.name} pattern={NAME} onChange={(e) => set(i, { name: e.target.value })} />
              </Field>
              <Field label={t('model.rule')}>
                <select
                  className="mt-1 block"
                  value={r.type}
                  onChange={(e) => setRule(newRule(e.target.value as Rule['type'], named, calendars))}
                >
                  {RULES.map((type) => (
                    <option key={type} value={type}>
                      {t(`model.rule_${type}`)}
                    </option>
                  ))}
                </select>
              </Field>
              <button type="button" className="link" onClick={() => onChange(derived.filter((_, j) => j !== i))}>
                {t('model.remove')}
              </button>
            </div>
            {r.type === 'group' && (
              <div className="space-y-1 text-sm">
                <div>
                  {t('model.groupOf')} {partSelect(r.part, (part) => setRule({ ...r, part }))}
                </div>
                {Object.entries(r.groups).map(([from, to], k) => (
                  <div key={k} className="flex gap-2">
                    <Input
                      placeholder={t('model.value')}
                      value={from}
                      onChange={(e) => {
                        const entries = Object.entries(r.groups);
                        entries[k] = [e.target.value, to];
                        setRule({ ...r, groups: Object.fromEntries(entries) });
                      }}
                    />
                    <span className="self-center">→</span>
                    <Input
                      placeholder={t('model.group')}
                      value={to}
                      onChange={(e) => setRule({ ...r, groups: { ...r.groups, [from]: e.target.value } })}
                    />
                  </div>
                ))}
                <button
                  type="button"
                  className="link"
                  onClick={() => setRule({ ...r, groups: { ...r.groups, [`value ${Object.keys(r.groups).length + 1}`]: '' } })}
                >
                  + {t('model.addValue')}
                </button>
                <Field label={t('model.otherwise')}>
                  <Input value={r.otherwise ?? ''} onChange={(e) => setRule({ ...r, otherwise: e.target.value || null })} />
                </Field>
              </div>
            )}
            {(r.type === 'join' || r.type === 'first_of') && (
              <div className="flex flex-wrap gap-2 text-sm">
                {named.map((p) => (
                  <label key={p.name} className="flex items-center gap-1">
                    <input
                      type="checkbox"
                      checked={r.parts.includes(p.name)}
                      onChange={(e) =>
                        setRule({ ...r, parts: e.target.checked ? [...r.parts, p.name] : r.parts.filter((x) => x !== p.name) })
                      }
                    />
                    {p.name}
                  </label>
                ))}
                {r.type === 'join' && (
                  <Field label={t('model.separator')}>
                    <Input value={r.separator ?? ' '} onChange={(e) => setRule({ ...r, separator: e.target.value })} />
                  </Field>
                )}
              </div>
            )}
            {r.type === 'date_part' && (
              <div className="flex gap-2 text-sm">
                {partSelect(r.part, (part) => setRule({ ...r, part }), 'date')}
                <select value={r.unit} onChange={(e) => setRule({ ...r, unit: e.target.value as typeof r.unit })}>
                  {(['year', 'quarter', 'month', 'week', 'day_of_week'] as const).map((u) => (
                    <option key={u} value={u}>
                      {t(`model.unit_${u}`)}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {r.type === 'period' && (
              <div className="flex flex-wrap items-center gap-2 text-sm">
                {partSelect(r.part, (part) => setRule({ ...r, part }), 'date')}
                {calendars.length === 0 ? (
                  <span className="text-muted-foreground">{t('model.noCalendar')}</span>
                ) : (
                  <select aria-label={t('model.calendar')} value={r.calendar} onChange={(e) => setRule({ ...r, calendar: e.target.value })}>
                    {calendars.map((c) => (
                      <option key={c.name} value={c.name}>
                        {words(c.body.label, me.locale) || c.name}
                      </option>
                    ))}
                  </select>
                )}
              </div>
            )}
            {r.type === 'arithmetic' && (
              <div className="flex gap-2 text-sm">
                {partSelect(String(r.left), (left) => setRule({ ...r, left }), 'number')}
                <select value={r.op} onChange={(e) => setRule({ ...r, op: e.target.value as typeof r.op })}>
                  {(['+', '-', '*', '/'] as const).map((op) => (
                    <option key={op}>{op}</option>
                  ))}
                </select>
                <Input
                  className="w-40"
                  value={String(r.right)}
                  onChange={(e) => {
                    const v = e.target.value;
                    setRule({ ...r, right: v !== '' && !Number.isNaN(Number(v)) ? Number(v) : v });
                  }}
                />
              </div>
            )}
            {r.type === 'bucket' && (
              <div className="space-y-1 text-sm">
                {partSelect(r.part, (part) => setRule({ ...r, part }), 'number')}
                <Field label={t('model.edges')}>
                  <Input
                    value={r.edges.join(', ')}
                    onChange={(e) => {
                      const edges = e.target.value
                        .split(',')
                        .map((x) => Number(x.trim()))
                        .filter((x) => !Number.isNaN(x));
                      setRule({ ...r, edges, labels: Array.from({ length: edges.length + 1 }, (_, k) => r.labels[k] ?? '') });
                    }}
                  />
                </Field>
                <Field label={t('model.bucketLabels')}>
                  <Input
                    value={r.labels.join(', ')}
                    onChange={(e) => setRule({ ...r, labels: e.target.value.split(',').map((x) => x.trim()) })}
                  />
                </Field>
              </div>
            )}
          </div>
        );
      })}
      <button
        type="button"
        className="link mt-2"
        onClick={() => onChange([...derived, { name: '', rule: newRule('group', named, calendars) }])}
        disabled={named.length === 0}
      >
        + {t('model.addDerived')}
      </button>
    </div>
  );
}
