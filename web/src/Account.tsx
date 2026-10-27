import { useState, type FormEvent } from 'react';
import { api, type User } from './api';

/** Your account: who you are signed in as, and changing your password. Changing it ends your sessions on other devices. */
export function Account({ user }: { user: User }) {
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = e.currentTarget;
    const data = new FormData(form);
    setDone(false);
    if (data.get('new_password') !== data.get('confirm')) {
      setError('The new password and its confirmation are different.');
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post('/password', { current_password: String(data.get('current_password')), new_password: String(data.get('new_password')) });
      form.reset();
      setDone(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <h2>Account</h2>
      <p className="note">
        Signed in as <strong dir="auto">{user.name}</strong> ({user.email}){user.is_admin ? ', an administrator' : ''}.
      </p>
      <form className="card new-chat" onSubmit={submit}>
        <h3>Change password</h3>
        <label>
          Current password
          <input name="current_password" type="password" autoComplete="current-password" required />
        </label>
        <label>
          New password (at least 12 characters)
          <input name="new_password" type="password" autoComplete="new-password" required minLength={12} />
        </label>
        <label>
          New password again
          <input name="confirm" type="password" autoComplete="new-password" required minLength={12} />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? 'Changing…' : 'Change password'}
        </button>
        {error && <p className="error" role="alert">{error}</p>}
        {done && <p className="note" role="status">Password changed. Your sessions on other devices have ended.</p>}
      </form>
    </section>
  );
}
