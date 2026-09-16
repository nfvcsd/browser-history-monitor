import { FormEvent, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { HistoryVisit, Overview, User } from "./types";

function fmtDate(value: string) {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function fmtNumber(value: number) {
  return new Intl.NumberFormat().format(value);
}

export default function App() {
  const [token, setToken] = useState(() => localStorage.getItem("adminToken") ?? "");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [history, setHistory] = useState<HistoryVisit[]>([]);
  const [selectedUser, setSelectedUser] = useState("");
  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const signedIn = Boolean(token);

  async function load(nextToken = token) {
    if (!nextToken) return;
    setLoading(true);
    setError("");
    try {
      const [overviewData, userData, historyData] = await Promise.all([
        api.overview(nextToken),
        api.users(nextToken),
        api.history(nextToken, { limit: "250" }),
      ]);
      setOverview(overviewData);
      setUsers(userData);
      setHistory(historyData);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (token) void load(token);
  }, []);

  async function applyFilters(event?: FormEvent) {
    event?.preventDefault();
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      setHistory(
        await api.history(token, {
          userId: selectedUser || undefined,
          q: query || undefined,
          domain: domain || undefined,
          limit: "500",
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = new FormData(event.currentTarget).get("token")?.toString().trim();
    if (!value) return;
    localStorage.setItem("adminToken", value);
    setToken(value);
    void load(value);
  }

  function logout() {
    localStorage.removeItem("adminToken");
    setToken("");
    setOverview(null);
    setUsers([]);
    setHistory([]);
  }

  const selectedEmail = useMemo(
    () => users.find((user) => user.id === selectedUser)?.email,
    [selectedUser, users],
  );

  if (!signedIn) {
    return (
      <main className="login-shell">
        <form className="login-card" onSubmit={login}>
          <span className="eyebrow">Milestone 1</span>
          <h1>Browser History Monitor</h1>
          <p>
            Enter the development administrator token. Google Workspace sign-in
            replaces this screen in the next milestone.
          </p>
          <input
            name="token"
            type="password"
            autoComplete="off"
            placeholder="DEV_ADMIN_TOKEN"
          />
          <button type="submit">Open dashboard</button>
        </form>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside>
        <div>
          <span className="eyebrow">NFVCSD</span>
          <h2>History</h2>
        </div>
        <nav>
          <button className="nav-active">Overview</button>
          <button>Users</button>
          <button>Domains</button>
          <button>Reports</button>
          <button>Audit Log</button>
          <button>Settings</button>
        </nav>
        <button className="ghost" onClick={logout}>Sign out</button>
      </aside>

      <main>
        <header>
          <div>
            <span className="eyebrow">Central console</span>
            <h1>Browser history</h1>
          </div>
          <button className="secondary" onClick={() => void load()}>
            Refresh
          </button>
        </header>

        {error && <div className="error">{error}</div>}

        <section className="stats">
          <article><span>Visits today</span><strong>{fmtNumber(overview?.visits_today ?? 0)}</strong></article>
          <article><span>Total visits</span><strong>{fmtNumber(overview?.visits ?? 0)}</strong></article>
          <article><span>Users</span><strong>{fmtNumber(overview?.users ?? 0)}</strong></article>
          <article><span>Domains</span><strong>{fmtNumber(overview?.domains ?? 0)}</strong></article>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <div>
              <span className="eyebrow">Investigation</span>
              <h2>{selectedEmail ? selectedEmail : "All users"}</h2>
            </div>
            <span className="muted">{loading ? "Loading…" : `${history.length} rows shown`}</span>
          </div>

          <form className="filters" onSubmit={applyFilters}>
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search URL, title, domain or email"
            />
            <input
              value={domain}
              onChange={(e) => setDomain(e.target.value)}
              placeholder="Domain"
            />
            <select value={selectedUser} onChange={(e) => setSelectedUser(e.target.value)}>
              <option value="">All users</option>
              {users.map((user) => (
                <option value={user.id} key={user.id}>{user.email}</option>
              ))}
            </select>
            <button type="submit">Apply filters</button>
          </form>

          <div className="history-list">
            {history.map((visit) => (
              <article className="visit" key={visit.id}>
                <div className="visit-time">{fmtDate(visit.visit_time)}</div>
                <div className="visit-main">
                  <strong>{visit.title || visit.domain || visit.url}</strong>
                  <a href={visit.url} target="_blank" rel="noreferrer">{visit.url}</a>
                  <div className="chips">
                    <span>{visit.user_email}</span>
                    {visit.domain && <span>{visit.domain}</span>}
                    {visit.transition && <span>{visit.transition}</span>}
                    {visit.is_local === false && <span>synced visit</span>}
                  </div>
                </div>
              </article>
            ))}
            {!loading && history.length === 0 && (
              <div className="empty">No history matches these filters.</div>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
