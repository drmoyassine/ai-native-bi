import { useCallback, useEffect, useState } from 'react';
import { api, type CalendarBody, type CalendarPeriod, type CalendarSummary, type Me } from './api';
import { Button } from './components/ui/button';
import { Card } from './components/ui/card';
import { Input } from './components/ui/input';
import { useTranslation } from './i18n';
import { PRIMARY_LANGUAGE } from './languages';
import { Field, WordsInput } from './Model';

// The organization's calendars (docs/data-model-spec.md § 4, TASK-043): its own periods, whatever it calls them. A calendar lists its
// periods with their dates, or repeats every year from a start day. An event's derived part says which period a date falls in. An admin
// changes them; everyone sees them.

const NAME = '^[a-z][a-z0-9_]{0,62}$';
const MONTHS = Array.from({ length: 12 }, (_, i) => String(i + 1).padStart(2, '0'));

function label(body: CalendarBody, locale: string): string {
  return body.label[locale] || body.label[PRIMARY_LANGUAGE] || '';
}

function startsText(starts: string, locale: string): string {
  const [m = 1, d = 1] = starts.split('-').map(Number);
  return new Date(2000, m - 1, d).toLocaleString(locale, { month: 'long', day: 'numeric' });
}

export function Calendars({ me }: { me: Me }) {
  const { t } = useTranslation();
  const [list, setList] = useState<CalendarSummary[] | null>(null);
  const [open, setOpen] = useState<{ name: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setList((await api.get<{ calendars: CalendarSummary[] }>('/calendars')).calendars);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  if (open) {
    const existing = open.name ? list?.find((c) => c.name === open.name) : undefined;
    return (
      <CalendarEditor
        me={me}
        existing={existing}
        taken={(list ?? []).map((c) => c.name)}
        onDone={(saved) => {
          if (saved) setList(saved);
          setOpen(null);
        }}
      />
    );
  }
  return (
    <section className="space-y-4">
      <div>
        <h2>{t('calendars.title')}</h2>
        <p className="text-sm text-muted-foreground">{t('calendars.intro')}</p>
      </div>
      {error && <p className="error">{error}</p>}
      {list && list.length === 0 && <p className="text-sm text-muted-foreground">{t('calendars.none')}</p>}
      {list?.map((c) => (
        <Card key={c.name} className="flex flex-wrap items-center justify-between gap-2 p-4">
          <div>
            <div className="font-medium">{label(c.body, me.locale) || c.name}</div>
            <div className="text-sm text-muted-foreground">
              {c.body.repeat
                ? t(`calendars.repeats_${c.body.repeat.every}`, { starts: startsText(c.body.repeat.starts, me.locale) })
                : t('calendars.listedCount', { count: c.body.periods?.length ?? 0 })}
              {c.used_by.length > 0 && ` · ${t('calendars.usedBy', { events: c.used_by.join(', ') })}`}
            </div>
          </div>
          {me.user.is_admin && (
            <Button variant="outline" onClick={() => setOpen({ name: c.name })}>
              {t('calendars.edit')}
            </Button>
          )}
        </Card>
      ))}
      {me.user.is_admin && <Button onClick={() => setOpen({ name: null })}>{t('calendars.new')}</Button>}
    </section>
  );
}

function CalendarEditor({
  me,
  existing,
  taken,
  onDone,
}: {
  me: Me;
  existing: CalendarSummary | undefined;
  taken: string[];
  onDone: (saved: CalendarSummary[] | null) => void;
}) {
  const { t } = useTranslation();
  const [name, setName] = useState(existing?.name ?? '');
  const [body, setBody] = useState<CalendarBody>(existing?.body ?? { label: {}, periods: [] });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (change: Partial<CalendarBody>) => setBody((b) => ({ ...b, ...change }));
  const periods = body.periods ?? [];
  const setPeriod = (i: number, change: Partial<CalendarPeriod>) =>
    set({ periods: periods.map((p, j) => (j === i ? { ...p, ...change } : p)) });
  const repeat = body.repeat;
  const [month, day] = (repeat?.starts ?? '01-01').split('-');

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!existing && taken.includes(name)) {
      setError(t('calendars.taken'));
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const clean: CalendarBody = repeat ? { label: body.label, description: body.description, repeat } : { ...body, repeat: undefined };
      const saved = await api.put<{ calendars: CalendarSummary[] }>(`/calendars/${name}`, clean);
      onDone(saved.calendars);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!existing || !window.confirm(t('calendars.removeConfirm'))) return;
    try {
      onDone((await api.delete<{ calendars: CalendarSummary[] }>(`/calendars/${existing.name}`)).calendars);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <form className="space-y-4" onSubmit={save}>
      <h2>{existing ? label(existing.body, me.locale) || existing.name : t('calendars.new')}</h2>
      <Card className="space-y-3 p-4">
        <Field label={t('calendars.name')} hint={t('calendars.nameHint')}>
          <Input required pattern={NAME} value={name} disabled={!!existing} onChange={(e) => setName(e.target.value)} />
        </Field>
        <WordsInput me={me} label={t('calendars.label')} value={body.label} onChange={(l) => set({ label: l })} />
        <fieldset className="space-y-1 text-sm">
          <legend className="mb-1">{t('calendars.shape')}</legend>
          <label className="!flex-row items-center gap-2">
            <input type="radio" checked={!repeat} onChange={() => set({ repeat: null, periods: periods })} />
            {t('calendars.listed')}
          </label>
          <label className="!flex-row items-center gap-2">
            <input type="radio" checked={!!repeat} onChange={() => set({ repeat: { every: 'year', starts: '01-01' }, periods: [] })} />
            {t('calendars.repeating')}
          </label>
        </fieldset>
      </Card>

      {repeat && (
        <Card className="flex flex-wrap items-end gap-3 p-4 text-sm">
          <Field label={t('calendars.every')}>
            <select
              className="mt-1 block"
              value={repeat.every}
              onChange={(e) => set({ repeat: { ...repeat, every: e.target.value as 'year' | 'quarter' } })}
            >
              <option value="year">{t('calendars.every_year')}</option>
              <option value="quarter">{t('calendars.every_quarter')}</option>
            </select>
          </Field>
          <Field label={t('calendars.startsMonth')}>
            <select
              className="mt-1 block"
              value={month}
              onChange={(e) => set({ repeat: { ...repeat, starts: `${e.target.value}-${day}` } })}
            >
              {MONTHS.map((m) => (
                <option key={m} value={m}>
                  {new Date(2000, Number(m) - 1, 1).toLocaleString(me.locale, { month: 'long' })}
                </option>
              ))}
            </select>
          </Field>
          <Field label={t('calendars.startsDay')} hint={t('calendars.startsDayHint')}>
            <Input
              className="mt-1 block w-20"
              type="number"
              min={1}
              max={28}
              value={Number(day)}
              onChange={(e) => set({ repeat: { ...repeat, starts: `${month}-${String(e.target.value).padStart(2, '0')}` } })}
            />
          </Field>
          <Field label={t('calendars.namedBy')}>
            <select
              className="mt-1 block"
              value={repeat.named_by ?? 'start'}
              onChange={(e) => set({ repeat: { ...repeat, named_by: e.target.value as 'start' | 'end' } })}
            >
              <option value="start">{t('calendars.namedBy_start')}</option>
              <option value="end">{t('calendars.namedBy_end')}</option>
            </select>
          </Field>
        </Card>
      )}

      {!repeat && (
        <Card className="space-y-2 p-4">
          <p className="text-sm text-muted-foreground">{t('calendars.periodsHint')}</p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  <th className="text-start">{t('calendars.code')}</th>
                  <th className="text-start">{t('calendars.periodLabel')}</th>
                  <th className="text-start">{t('calendars.starts')}</th>
                  <th className="text-start">{t('calendars.ends')}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {periods.map((p, i) => (
                  <tr key={i}>
                    <td>
                      <Input
                        required
                        aria-label={t('calendars.code')}
                        value={p.code}
                        onChange={(e) => setPeriod(i, { code: e.target.value })}
                      />
                    </td>
                    <td>
                      <Input
                        aria-label={t('calendars.periodLabel')}
                        dir="auto"
                        value={p.label?.[me.locale] ?? p.label?.[PRIMARY_LANGUAGE] ?? ''}
                        onChange={(e) => setPeriod(i, { label: { ...p.label, [me.locale]: e.target.value } })}
                      />
                    </td>
                    <td>
                      <Input
                        required
                        type="date"
                        aria-label={t('calendars.starts')}
                        value={p.starts}
                        onChange={(e) => setPeriod(i, { starts: e.target.value })}
                      />
                    </td>
                    <td>
                      <Input
                        required
                        type="date"
                        aria-label={t('calendars.ends')}
                        value={p.ends}
                        onChange={(e) => setPeriod(i, { ends: e.target.value })}
                      />
                    </td>
                    <td>
                      <button type="button" className="link" onClick={() => set({ periods: periods.filter((_, j) => j !== i) })}>
                        {t('model.remove')}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Button type="button" variant="outline" onClick={() => set({ periods: [...periods, { code: '', starts: '', ends: '' }] })}>
            {t('calendars.addPeriod')}
          </Button>
        </Card>
      )}

      {error && <p className="error">{error}</p>}
      {existing && existing.used_by.length > 0 && (
        <p className="text-sm text-muted-foreground">{t('calendars.appliesNext', { events: existing.used_by.join(', ') })}</p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>
          {t('calendars.save')}
        </Button>
        <Button type="button" variant="outline" onClick={() => onDone(null)}>
          {t('calendars.cancel')}
        </Button>
        {existing && (
          <Button type="button" variant="outline" onClick={() => void remove()}>
            {t('calendars.remove')}
          </Button>
        )}
      </div>
    </form>
  );
}
