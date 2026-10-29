import { useEffect, useState, type FormEvent } from 'react';
import { api, ApiError, type Organization, type User } from './api';
import { Button } from './components/ui/button';
import { Card } from './components/ui/card';
import { Input } from './components/ui/input';
import { useTranslation } from './i18n';
import { applyAccent } from './languages';

/** The sign-in page, after the AMS's: the organization's name and accent colour (the one read without signing in), then the form. */
export function Login({ onSignedIn }: { onSignedIn: (user: User) => void }) {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [branding, setBranding] = useState<Organization | null>(null);

  useEffect(() => {
    let live = true;
    api
      .get<Organization>('/public/branding')
      .then((b) => {
        if (live) setBranding(b);
      })
      .catch(() => undefined);
    return () => {
      live = false;
    };
  }, []);
  useEffect(() => {
    applyAccent(branding?.accent_color);
    return () => applyAccent(null);
  }, [branding?.accent_color]);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const { user } = await api.post<{ user: User }>('/session', { email: form.get('email'), password: form.get('password') });
      onSignedIn(user);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? t('login.wrong') : String((err as Error).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <p className="mb-4 mt-0 text-center text-lg font-medium">{branding?.name || t('appName')}</p>
        <h1 className="mb-4 text-xl font-semibold">{t('login.title')}</h1>
        <form onSubmit={submit} className="space-y-3">
          <label className="block text-sm">
            {t('login.email')}
            <Input name="email" type="email" autoComplete="username" required autoFocus />
          </label>
          <label className="block text-sm">
            {t('login.password')}
            <Input name="password" type="password" autoComplete="current-password" required />
          </label>
          {error && (
            <p className="text-sm text-[var(--error)]" role="alert">
              {error}
            </p>
          )}
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? t('login.busy') : t('login.submit')}
          </Button>
        </form>
      </Card>
    </main>
  );
}
