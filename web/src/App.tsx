import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type Me } from './api';
import { Chat } from './Chat';
import { ChartPage } from './ChartPage';
import { Connect } from './Connect';
import { Button } from './components/ui/button';
import { useTranslation } from './i18n';
import i18n from './i18n';
import { applyAccent, applyLanguage, PRIMARY_LANGUAGE, type LanguageInfo } from './languages';
import { Login } from './Login';
import { Metrics } from './Metrics';
import { Settings, type SettingsTab } from './Settings';

type Page = 'chat' | 'chart' | 'connect' | 'metrics' | 'settings';

const navLink = 'block w-full rounded-md border-0 bg-transparent px-3 py-2 text-start text-sm hover:bg-background';
const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/** The shell, after the AMS's (DEC-038): a sidebar at `lg` and up; below it a slim top bar opens the same navigation in a drawer. */
export function App() {
  const { t } = useTranslation();
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [languages, setLanguages] = useState<LanguageInfo[]>([]);
  const [page, setPage] = useState<Page>('chat');
  const [settingsTab, setSettingsTab] = useState<SettingsTab>('organization');
  const [drawer, setDrawer] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const wasOpen = useRef(false);

  const load = useCallback(async () => {
    try {
      setMe(await api.get<Me>('/me'));
      setLanguages((await api.get<{ languages: LanguageInfo[] }>('/languages')).languages);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setMe(null);
      else throw err;
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const locale = me?.locale ?? PRIMARY_LANGUAGE;
  const accent = me?.organization.accent_color;
  useEffect(() => {
    applyLanguage(languages.find((l) => l.code === locale) ?? null);
    void i18n.changeLanguage(locale);
  }, [locale, languages]);
  useEffect(() => {
    applyAccent(accent);
    return () => applyAccent(null);
  }, [accent]);

  const close = useCallback(() => setDrawer(false), []);
  useEffect(() => {
    if (!drawer) {
      if (wasOpen.current) {
        wasOpen.current = false;
        menuButton.current?.focus();
      }
      return undefined;
    }
    wasOpen.current = true;
    panel.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        setDrawer(false);
        return;
      }
      if (e.key !== 'Tab' || !panel.current) return;
      const items = [...panel.current.querySelectorAll<HTMLElement>(FOCUSABLE)];
      const first = items[0];
      const last = items[items.length - 1];
      if (!first || !last) return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    window.addEventListener('keydown', onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const wide = typeof window.matchMedia === 'function' ? window.matchMedia('(min-width: 64rem)') : null;
    const onWide = (e: MediaQueryListEvent) => {
      if (e.matches) setDrawer(false);
    };
    wide?.addEventListener('change', onWide);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.body.style.overflow = overflow;
      wide?.removeEventListener('change', onWide);
    };
  }, [drawer]);

  async function signOut() {
    close();
    await api.delete('/session');
    setMe(null);
  }

  async function chooseLanguage(code: string) {
    await api.put('/me/language', { language: code });
    await load();
  }

  if (me === undefined) return <p className="mt-[30vh] text-center text-muted-foreground">{t('loading')}</p>;
  if (me === null) return <Login onSignedIn={() => void load()} />;

  const { user, organization: org } = me;
  const orgName = (locale !== PRIMARY_LANGUAGE && org.name_secondary) || org.name || t('appName');
  const secondary = languages.find((l) => l.code === org.secondary_language);
  const go = (p: Page) => {
    setPage(p);
    close();
  };
  const item = (p: Page, label: string) => (
    <button
      key={p}
      type="button"
      className={`${navLink} ${page === p ? '!bg-background font-medium' : ''}`}
      aria-current={page === p ? 'page' : undefined}
      onClick={() => go(p)}
    >
      {label}
    </button>
  );
  const languageMenu = secondary && (
    <label className="flex items-center gap-2 text-sm text-muted-foreground">
      <span className="sr-only">{t('language.label')}</span>
      <select className="w-full" value={locale} onChange={(e) => void chooseLanguage(e.target.value)}>
        <option value={PRIMARY_LANGUAGE}>English</option>
        <option value={secondary.code}>{secondary.native_name}</option>
      </select>
    </label>
  );
  const links = (
    <>
      <nav className="flex flex-col gap-1" aria-label={t('nav.main')}>
        {item('chat', t('nav.ask'))}
        {item('chart', t('nav.chart'))}
        {item('connect', t('nav.connect'))}
        {item('metrics', t('nav.metrics'))}
      </nav>
      <div className="mt-6 flex flex-col gap-1">
        {item('settings', t('nav.settings'))}
        <p className="m-0 px-3 pt-2 text-xs text-muted-foreground" dir="auto">
          {t('nav.signedInAs', { name: user.name })}
        </p>
        <Button variant="ghost" className="w-full justify-start border-0 px-3 font-normal" onClick={() => void signOut()}>
          {t('signOut')}
        </Button>
      </div>
    </>
  );
  const iconButton =
    'flex size-10 shrink-0 items-center justify-center rounded-md border-0 bg-transparent text-xl leading-none hover:bg-background';

  return (
    <div className="min-h-screen lg:flex">
      <header className="sticky top-0 z-30 flex items-center gap-2 border-b border-border bg-muted px-4 py-1.5 lg:hidden">
        <button
          ref={menuButton}
          type="button"
          aria-label={t('nav.openMenu')}
          aria-expanded={drawer}
          aria-controls="app-drawer"
          onClick={() => setDrawer(true)}
          className={`-ms-2 ${iconButton}`}
        >
          <span aria-hidden="true">☰</span>
        </button>
        <p className="m-0 min-w-0 flex-1 truncate text-sm text-muted-foreground">{orgName}</p>
        {languageMenu && <div className="shrink-0">{languageMenu}</div>}
      </header>
      <aside className="hidden w-56 shrink-0 border-e border-border bg-muted p-4 lg:block">
        <p className="mb-3 mt-0 break-words text-sm text-muted-foreground" data-testid="organization-name">
          {orgName}
        </p>
        {languageMenu && <div className="mb-6">{languageMenu}</div>}
        {!drawer && links}
      </aside>
      {drawer && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" aria-hidden="true" onClick={close} />
          <div
            ref={panel}
            id="app-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={t('nav.menu')}
            className="drawer-in absolute inset-y-0 start-0 flex w-72 max-w-[85vw] flex-col overflow-y-auto border-e border-border bg-muted p-4 shadow-xl"
          >
            <div className="mb-6 flex items-start gap-2">
              <p className="m-0 min-w-0 flex-1 break-words text-sm text-muted-foreground">{orgName}</p>
              <button type="button" aria-label={t('nav.closeMenu')} onClick={close} className={`-me-2 ${iconButton}`}>
                <span aria-hidden="true">✕</span>
              </button>
            </div>
            {links}
          </div>
        </div>
      )}
      <main className="min-w-0 flex-1 p-4 sm:p-6 lg:p-8">
        {page === 'chat' && <Chat />}
        {page === 'chart' && <ChartPage />}
        {page === 'connect' && <Connect user={user} />}
        {page === 'metrics' && <Metrics />}
        {page === 'settings' && (
          <Settings me={me} languages={languages} onSaved={() => void load()} tab={settingsTab} onTab={setSettingsTab} />
        )}
      </main>
    </div>
  );
}
