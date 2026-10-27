import { useEffect, useState } from 'react';
import { api, ApiError, type User } from './api';
import { Account } from './Account';
import { Chat } from './Chat';
import { ChartPage } from './ChartPage';
import { Login } from './Login';
import { Providers } from './Providers';
import { Tokens } from './Tokens';
import { Uploads } from './Uploads';

type Page = 'chat' | 'chart' | 'uploads' | 'models' | 'tokens' | 'account';

export function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [datasets, setDatasets] = useState<string[]>([]);
  const [page, setPage] = useState<Page>('chat');

  async function load() {
    try {
      const me = await api.get<{ user: User; datasets: string[] }>('/me');
      setUser(me.user);
      setDatasets(me.datasets);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setUser(null);
      else throw err;
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function signOut() {
    await api.delete('/session');
    setUser(null);
  }

  if (user === undefined) return <p className="hint center">Loading…</p>;
  if (user === null) return <Login onSignedIn={() => void load()} />;

  return (
    <>
      <header>
        <strong>AI-native BI</strong>
        <nav>
          <button className={page === 'chat' ? 'active' : ''} onClick={() => setPage('chat')}>
            Ask
          </button>
          <button className={page === 'chart' ? 'active' : ''} onClick={() => setPage('chart')}>
            Chart
          </button>
          <button className={page === 'uploads' ? 'active' : ''} onClick={() => setPage('uploads')}>
            Uploads
          </button>
          <button className={page === 'tokens' ? 'active' : ''} onClick={() => setPage('tokens')}>
            Access tokens
          </button>
          {user.is_admin && (
            <button className={page === 'models' ? 'active' : ''} onClick={() => setPage('models')}>
              Models
            </button>
          )}
        </nav>
        <span className="who">
          <button className="link" onClick={() => setPage('account')} title="Your account and password">
            {user.name}
          </button>
          <button className="link" onClick={() => void signOut()}>
            Sign out
          </button>
        </span>
      </header>
      <main className={page === 'chat' ? 'wide' : ''}>
        {page === 'chat' && <Chat />}
        {page === 'chart' && <ChartPage />}
        {page === 'uploads' && <Uploads datasets={datasets} />}
        {page === 'models' && user.is_admin && <Providers />}
        {page === 'tokens' && <Tokens user={user} />}
        {page === 'account' && <Account user={user} />}
      </main>
    </>
  );
}
