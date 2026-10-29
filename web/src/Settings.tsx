import { useEffect, useState, type FormEvent } from 'react';
import { api, type Me, type Organization, type Template } from './api';
import { Button } from './components/ui/button';
import { Card } from './components/ui/card';
import { Input } from './components/ui/input';
import { useTranslation } from './i18n';
import { isReadableAccent, PRIMARY_LANGUAGE, type LanguageInfo } from './languages';

const DEFAULT_ACCENT = '#2b3a5c'; // close to the default --primary, for the colour picker's starting point

/** Settings → Organization (DEC-038): the organization's name, its secondary language, the default interface language and its accent. */
export function Settings({ me, languages, onSaved }: { me: Me; languages: LanguageInfo[]; onSaved: () => void }) {
  const { t } = useTranslation();
  const org = me.organization;
  const canEdit = me.user.is_admin;
  const [draft, setDraft] = useState<Organization>(org);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  useEffect(() => {
    api
      .get<{ templates: Template[] }>('/templates')
      .then((r) => setTemplates(r.templates))
      .catch(() => undefined);
  }, []);
  const secondary = languages.find((l) => l.code === draft.secondary_language);
  const accentProblem = draft.accent_color && !isReadableAccent(draft.accent_color);

  function set<K extends keyof Organization>(key: K, value: Organization[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
    setSaved(false);
  }

  async function save(e: FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.put('/organization', {
        name: draft.name,
        name_secondary: draft.secondary_language ? draft.name_secondary || null : null,
        secondary_language: draft.secondary_language,
        default_locale: draft.secondary_language ? draft.default_locale : PRIMARY_LANGUAGE,
        accent_color: draft.accent_color,
        installed_templates: draft.installed_templates,
      });
      setSaved(true);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <section className="max-w-2xl">
      <h1>{t('settings.title')}</h1>
      <Card>
        <h2 className="mt-0">{t('settings.organization')}</h2>
        <p className="text-sm text-muted-foreground">{t('settings.intro')}</p>
        {!canEdit && <p className="text-sm text-muted-foreground">{t('settings.readOnly')}</p>}
        <form onSubmit={save} className="mt-4 space-y-4">
          <fieldset disabled={!canEdit} className="space-y-4 border-0 p-0">
            <label className="block text-sm">
              {t('settings.name')}
              <Input value={draft.name} maxLength={200} onChange={(e) => set('name', e.target.value)} />
            </label>
            <label className="block text-sm">
              {t('settings.secondaryLanguage')}
              <select
                className="mt-1 block w-full"
                value={draft.secondary_language ?? ''}
                onChange={(e) => set('secondary_language', e.target.value || null)}
              >
                <option value="">{t('settings.secondaryNone')}</option>
                {languages
                  .filter((l) => l.code !== PRIMARY_LANGUAGE)
                  .map((l) => (
                    <option key={l.code} value={l.code}>
                      {l.native_name} ({l.name_en})
                    </option>
                  ))}
              </select>
              <span className="mt-1 block text-muted-foreground">{t('settings.secondaryHint')}</span>
            </label>
            {secondary && (
              <>
                <label className="block text-sm">
                  {t('settings.nameSecondary', { language: secondary.name_en })}
                  <Input
                    dir={secondary.dir}
                    lang={secondary.code}
                    value={draft.name_secondary ?? ''}
                    maxLength={200}
                    onChange={(e) => set('name_secondary', e.target.value)}
                  />
                </label>
                <label className="block text-sm">
                  {t('settings.defaultLocale')}
                  <select
                    className="mt-1 block w-full"
                    value={draft.default_locale}
                    onChange={(e) => set('default_locale', e.target.value)}
                  >
                    <option value={PRIMARY_LANGUAGE}>English</option>
                    <option value={secondary.code}>{secondary.native_name}</option>
                  </select>
                </label>
              </>
            )}
            <div className="text-sm">
              {t('settings.accent')}
              <div className="mt-1 flex flex-wrap items-center gap-3">
                <input
                  type="color"
                  aria-label={t('settings.accent')}
                  className="h-10 w-16 p-1"
                  value={draft.accent_color ?? DEFAULT_ACCENT}
                  onChange={(e) => set('accent_color', e.target.value)}
                />
                <span
                  className="rounded-md px-4 py-2 text-sm font-medium text-white"
                  style={{ background: draft.accent_color ?? 'var(--primary)' }}
                >
                  {t('settings.accentPreview')}
                </span>
                {draft.accent_color && (
                  <Button type="button" variant="outline" onClick={() => set('accent_color', null)}>
                    {t('settings.accentDefault')}
                  </Button>
                )}
              </div>
              <span className="mt-1 block text-muted-foreground">{t('settings.accentHint')}</span>
              {accentProblem && <span className="mt-1 block text-[var(--error)]">{t('settings.accentUnreadable')}</span>}
            </div>
            <fieldset className="border-0 p-0 text-sm">
              <legend className="mb-1">{t('settings.templates')}</legend>
              <span className="mb-2 block text-muted-foreground">{t('settings.templatesHint')}</span>
              {templates.length === 0 && <span className="block text-muted-foreground">{t('settings.templatesNone')}</span>}
              {templates.map((tpl) => (
                <label key={tpl.name} className="flex items-start gap-2 py-1">
                  <input
                    type="checkbox"
                    className="mt-1"
                    checked={draft.installed_templates.includes(tpl.name)}
                    onChange={(e) =>
                      set(
                        'installed_templates',
                        e.target.checked
                          ? [...draft.installed_templates, tpl.name]
                          : draft.installed_templates.filter((n) => n !== tpl.name),
                      )
                    }
                  />
                  <span>
                    <span className="font-medium">{tpl.label[me.locale] ?? tpl.label.en ?? tpl.name}</span>
                    <span className="block text-muted-foreground">
                      {tpl.datasets.map((d) => d.label[me.locale] ?? d.label.en ?? d.name).join(', ')}
                    </span>
                  </span>
                </label>
              ))}
            </fieldset>
          </fieldset>
          {error && <p className="text-sm text-[var(--error)]">{error}</p>}
          {saved && <p className="text-sm text-[var(--ok)]">{t('settings.saved')}</p>}
          {canEdit && (
            <Button type="submit" disabled={Boolean(accentProblem)}>
              {t('settings.save')}
            </Button>
          )}
        </form>
      </Card>
    </section>
  );
}
