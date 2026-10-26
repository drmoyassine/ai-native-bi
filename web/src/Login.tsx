import { useState, type FormEvent } from 'react';
import { api, ApiError, type User } from './api';

export function Login({ onSignedIn }: { onSignedIn: (user: User) => void }) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const { user } = await api.post<{ user: User }>('/session', { email: form.get('email'), password: form.get('password') });
      onSignedIn(user);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401 ? 'Wrong email or password.' : String((err as Error).message));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login">
      <form onSubmit={submit} className="card">
        <h1>AI-native BI</h1>
        <label>
          Email
          <input name="email" type="email" autoComplete="username" required autoFocus />
        </label>
        <label>
          Password
          <input name="password" type="password" autoComplete="current-password" required />
        </label>
        {error && <p className="error" role="alert">{error}</p>}
        <button type="submit" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </main>
  );
}
