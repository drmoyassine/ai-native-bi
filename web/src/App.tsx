import { useEffect, useState } from 'react';
import { api, ApiError, type User } from './api';
import { ChartPage } from './ChartPage';
import { Login } from './Login';
import { Uploads } from './Uploads';

type Page = 'chart' | 'uploads';

export function App() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [datasets, setDatasets] = useState<string[]>([]);
  const [page, setPage] = useState<Page>('chart');

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
          <button className={page === 'chart' ? 'active' : ''} onClick={() => setPage('chart')}>
            Chart
          </button>
          <button className={page === 'uploads' ? 'active' : ''} onClick={() => setPage('uploads')}>
            Uploads
          </button>
        </nav>
        <span className="who">
          {user.name}
          <button className="link" onClick={() => void signOut()}>
            Sign out
          </button>
        </span>
      </header>
      <main>{page === 'chart' ? <ChartPage /> : <Uploads datasets={datasets} />}</main>
    </>
  );
}
