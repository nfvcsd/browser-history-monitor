import { FormEvent, useEffect, useState } from "react";
import {
  BrowserRouter,
  Link,
  NavLink,
  Route,
  Routes,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { api } from "./api";
import ReportsPage from "./ReportsPage";
import AuthGate, { AdminIdentity } from "./AuthGate";
import type { HistoryVisit } from "./types";

const PAGE_SIZE = 100;
function fmtDate(value: string | null) {
  return value
    ? new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "Never synced";
}
const fmtNumber = (value: number) => new Intl.NumberFormat().format(value);

// Ignore results from requests superseded by navigation, filters, refresh or logout.
function useData<T>(fetcher: () => Promise<T>, key: string) {
  const [state, setState] = useState<{
    data?: T;
    loading: boolean;
    error: string;
  }>({ loading: true, error: "" });
  useEffect(() => {
    let active = true;
    setState({ loading: true, error: "" });
    fetcher()
      .then((data) => {
        if (active) setState({ data, loading: false, error: "" });
      })
      .catch((error) => {
        if (active)
          setState({ loading: false, error: String(error.message ?? error) });
      });
    return () => {
      active = false;
    };
  }, [key]);
  return state;
}
function Status({ loading, error }: { loading: boolean; error: string }) {
  return (
    <>
      {loading && (
        <p role="status" className="muted">
          Loading…
        </p>
      )}
      {error && (
        <div role="alert" className="error">
          {error}. Check your connection and administrator token, then refresh.
        </div>
      )}
    </>
  );
}
function Pager({
  count,
  params,
  setParams,
}: {
  count: number;
  params: URLSearchParams;
  setParams: (p: URLSearchParams) => void;
}) {
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  function move(next: number) {
    const p = new URLSearchParams(params);
    p.set("offset", String(next));
    setParams(p);
  }
  return (
    <div className="pagination">
      <button
        className="secondary"
        disabled={!offset}
        onClick={() => move(Math.max(0, offset - PAGE_SIZE))}
      >
        Previous
      </button>
      <span>{count ? `${offset + 1}–${offset + count}` : "No rows"}</span>
      <button
        className="secondary"
        disabled={count < PAGE_SIZE}
        onClick={() => move(offset + PAGE_SIZE)}
      >
        Next
      </button>
    </div>
  );
}
function HistoryList({ visits }: { visits: HistoryVisit[] }) {
  return (
    <div className="history-list">
      {visits.map((visit) => (
        <article className="visit" key={visit.id}>
          <div className="visit-time">{fmtDate(visit.visit_time)}</div>
          <div className="visit-main">
            <strong>{visit.title || visit.domain || visit.url}</strong>
            {/^https?:\/\//i.test(visit.url) ? (
              <a href={visit.url} target="_blank" rel="noreferrer">
                {visit.url}
              </a>
            ) : (
              <span>{visit.url}</span>
            )}
            <div className="chips">
              <span>{visit.user_email}</span>
              {visit.domain && <span>{visit.domain}</span>}
              {visit.device_name && <span>{visit.device_name}</span>}
              {visit.transition && <span>{visit.transition}</span>}
              {visit.is_local === false && <span>synced visit</span>}
            </div>
          </div>
        </article>
      ))}
      {!visits.length && (
        <div className="empty">No history matches these filters.</div>
      )}
    </div>
  );
}
function applyForm(
  event: FormEvent<HTMLFormElement>,
  params: URLSearchParams,
  setParams: (p: URLSearchParams) => void,
) {
  event.preventDefault();
  const next = new URLSearchParams(params);
  new FormData(event.currentTarget).forEach((value, key) => {
    const text = String(value).trim();
    if (text) next.set(key, text);
    else next.delete(key);
  });
  next.delete("offset");
  setParams(next);
}
type PageProps = { token: string; revision: number };
function HistoryPage({
  token,
  revision,
  overview = false,
  userId,
  exactDomain,
}: PageProps & { overview?: boolean; userId?: string; exactDomain?: string }) {
  const [params, setParams] = useSearchParams();
  const key = `${token}:${revision}:${params}:${userId}:${exactDomain}:${overview}`;
  const state = useData(async () => {
    const [users, stats, person, visits] = await Promise.all([
      api.users(token),
      overview ? api.overview(token) : null,
      userId ? api.user(token, userId) : null,
      api.history(token, {
        userId: userId || params.get("user_id") || undefined,
        exactDomain,
        domain: params.get("domain") || undefined,
        q: params.get("q") || undefined,
        start: params.get("start") || undefined,
        end: params.get("end") || undefined,
        offset: params.get("offset") || "0",
        limit: String(PAGE_SIZE),
      }),
    ]);
    return { users, stats, person, visits };
  }, key);
  const data = state.data;
  return (
    <>
      {!overview && (
        <p>
          <Link
            to={
              userId
                ? "/users"
                : `/domains?${new URLSearchParams([...params].filter(([k]) => ["user_id", "start", "end"].includes(k)))}`
            }
          >
            ← {userId ? "Users" : "Domains"}
          </Link>
        </p>
      )}
      <Status {...state} />
      {data?.stats && (
        <section className="stats">
          {[
            ["Visits today", data.stats.visits_today],
            ["Total visits", data.stats.visits],
            ["Users", data.stats.users],
            ["Domains", data.stats.domains],
          ].map(([label, value]) => (
            <article key={label}>
              <span>{label}</span>
              <strong>{fmtNumber(Number(value))}</strong>
            </article>
          ))}
        </section>
      )}
      {data?.person && (
        <section className="stats">
          <article>
            <span>Last sync</span>
            <b>{fmtDate(data.person.last_sync_at)}</b>
          </article>
          <article>
            <span>Devices</span>
            <strong>{fmtNumber(data.person.device_count)}</strong>
          </article>
          <article>
            <span>Visits</span>
            <strong>{fmtNumber(data.person.visit_count)}</strong>
          </article>
        </section>
      )}
      <section className="panel">
        <div className="panel-heading">
          <div>
            <span className="eyebrow">Investigation</span>
            <h2>
              {data?.person?.email ||
                exactDomain ||
                data?.users.find((u) => u.id === params.get("user_id"))
                  ?.email ||
                "All users"}
            </h2>
          </div>
          <span className="muted">
            {data ? `${data.visits.length} rows shown` : ""}
          </span>
        </div>
        <form
          key={`${params}:${data?.users.length}`}
          className="filters"
          onSubmit={(e) => applyForm(e, params, setParams)}
        >
          <input
            aria-label="Search history"
            name="q"
            defaultValue={params.get("q") || ""}
            placeholder="Search URL, title, domain or email"
          />
          {exactDomain === undefined && (
            <input
              aria-label="Domain"
              name="domain"
              defaultValue={params.get("domain") || ""}
              placeholder="Domain"
            />
          )}
          {!userId && (
            <select
              aria-label="User"
              name="user_id"
              defaultValue={params.get("user_id") || ""}
            >
              <option value="">All users</option>
              {data?.users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.email}
                </option>
              ))}
            </select>
          )}
          <button>Apply filters</button>
        </form>
        {(params.get("start") || params.get("end")) && (
          <p className="muted">
            Activity range: {params.get("start") || "Beginning"} —{" "}
            {params.get("end") || "Now"}
          </p>
        )}
        {data && (
          <>
            <HistoryList visits={data.visits} />
            <Pager
              count={data.visits.length}
              params={params}
              setParams={setParams}
            />
          </>
        )}
      </section>
    </>
  );
}
function UsersPage({ token, revision }: PageProps) {
  const [params, setParams] = useSearchParams();
  const state = useData(
    () =>
      api.userSummaries(
        token,
        new URLSearchParams({
          q: params.get("q") || "",
          offset: params.get("offset") || "0",
          limit: String(PAGE_SIZE),
        }),
      ),
    `${token}:${revision}:${params}`,
  );
  return (
    <section className="panel">
      <h2>Monitored users</h2>
      <form
        key={params.toString()}
        className="filters"
        onSubmit={(e) => applyForm(e, params, setParams)}
      >
        <input
          aria-label="Search users"
          name="q"
          defaultValue={params.get("q") || ""}
          placeholder="Search email or name"
        />
        <button>Search</button>
      </form>
      <Status {...state} />
      {state.data && (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th>Last sync</th>
                  <th>Devices</th>
                  <th>Visits</th>
                </tr>
              </thead>
              <tbody>
                {state.data.map((u) => (
                  <tr key={u.id}>
                    <td>
                      <Link to={`/users/${u.id}`}>{u.email}</Link>
                      {u.display_name && (
                        <div className="muted">{u.display_name}</div>
                      )}
                    </td>
                    <td>{fmtDate(u.last_sync_at)}</td>
                    <td>{fmtNumber(u.device_count)}</td>
                    <td>{fmtNumber(u.visit_count)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!state.data.length && (
            <p className="empty">No users match this search.</p>
          )}
          <Pager
            count={state.data.length}
            params={params}
            setParams={setParams}
          />
        </>
      )}
    </section>
  );
}
function DomainsPage({ token, revision }: PageProps) {
  const [params, setParams] = useSearchParams();
  const state = useData(async () => {
    const query = new URLSearchParams(params);
    query.set("limit", String(PAGE_SIZE));
    for (const name of ["start", "end"]) {
      if (query.get(name))
        query.set(name, new Date(query.get(name)!).toISOString());
    }
    const [domains, users] = await Promise.all([
      api.domains(token, query),
      api.users(token),
    ]);
    return { domains, users };
  }, `${token}:${revision}:${params}`);
  return (
    <section className="panel">
      <h2>Domains</h2>
      <p className="muted">
        Counts and first/last activity reflect the selected user and time range.
        Times use your local timezone.
      </p>
      <form
        key={`${params}:${state.data?.users.length}`}
        className="filters domain-filters"
        onSubmit={(e) => applyForm(e, params, setParams)}
      >
        <input
          aria-label="Search domains"
          name="q"
          placeholder="Search domains"
          defaultValue={params.get("q") || ""}
        />
        <select
          aria-label="User"
          name="user_id"
          defaultValue={params.get("user_id") || ""}
        >
          <option value="">All users</option>
          {state.data?.users.map((u) => (
            <option key={u.id} value={u.id}>
              {u.email}
            </option>
          ))}
        </select>
        <label>
          From
          <input
            name="start"
            type="datetime-local"
            defaultValue={params.get("start") || ""}
          />
        </label>
        <label>
          Through
          <input
            name="end"
            type="datetime-local"
            defaultValue={params.get("end") || ""}
          />
        </label>
        <button>Apply filters</button>
      </form>
      <Status {...state} />
      {state.data && (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Domain</th>
                  <th>Visits</th>
                  <th>Unique users</th>
                  <th>First activity</th>
                  <th>Last activity</th>
                </tr>
              </thead>
              <tbody>
                {state.data.domains.map((d) => {
                  const drill = new URLSearchParams(
                    [...params].filter(([k]) =>
                      ["user_id", "start", "end"].includes(k),
                    ),
                  );
                  return (
                    <tr key={d.domain}>
                      <td>
                        <Link
                          to={`/domains/${encodeURIComponent(d.domain)}?${drill}`}
                        >
                          {d.domain}
                        </Link>
                      </td>
                      <td>{fmtNumber(d.visit_count)}</td>
                      <td>{fmtNumber(d.unique_users)}</td>
                      <td>{fmtDate(d.first_activity)}</td>
                      <td>{fmtDate(d.last_activity)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {!state.data.domains.length && (
            <p className="empty">No domains match these filters.</p>
          )}
          <Pager
            count={state.data.domains.length}
            params={params}
            setParams={setParams}
          />
        </>
      )}
    </section>
  );
}
function UserHistory(props: PageProps) {
  const { userId } = useParams();
  return <HistoryPage {...props} userId={userId} />;
}
function DomainHistory(props: PageProps) {
  const { domain } = useParams();
  return <HistoryPage {...props} exactDomain={domain} />;
}
function Console({
  token,
  identity,
  logout,
}: {
  token: string;
  identity: AdminIdentity;
  logout: () => void;
}) {
  const [revision, setRevision] = useState(0);
  const props = { token, revision };
  return (
    <div className="app-shell">
      <aside>
        <div>
          <span className="eyebrow">NFVCSD</span>
          <h2>History</h2>
        </div>
        <nav aria-label="Main navigation">
          <NavLink to="/" end>
            Overview
          </NavLink>
          <NavLink to="/users">Users</NavLink>
          <NavLink to="/domains">Domains</NavLink>
          <NavLink to="/reports">Reports</NavLink>
          {["Audit Log", "Settings"].map((label) => (
            <button disabled key={label}>
              {label}
              <small>Not yet implemented</small>
            </button>
          ))}
        </nav>
        <p className="signed-in-user">
          {identity.email || "Development administrator"}
        </p>
        <button className="ghost" onClick={logout}>
          Sign out
        </button>
      </aside>
      <main>
        <header>
          <div>
            <span className="eyebrow">Central console</span>
            <h1>Browser history</h1>
          </div>
          <button
            className="secondary"
            onClick={() => setRevision((v) => v + 1)}
          >
            Refresh
          </button>
        </header>
        <Routes>
          <Route path="/" element={<HistoryPage {...props} overview />} />
          <Route path="/users" element={<UsersPage {...props} />} />
          <Route path="/users/:userId" element={<UserHistory {...props} />} />
          <Route path="/domains" element={<DomainsPage {...props} />} />
          <Route path="/reports" element={<ReportsPage {...props} />} />
          <Route
            path="/domains/:domain"
            element={<DomainHistory {...props} />}
          />
          <Route
            path="*"
            element={
              <section className="panel">
                <h2>Page not found</h2>
                <Link to="/">Go to Overview</Link>
              </section>
            }
          />
        </Routes>
      </main>
    </div>
  );
}
export default function App() {
  return (
    <BrowserRouter>
      <AuthGate>{(props) => <Console {...props} />}</AuthGate>
    </BrowserRouter>
  );
}
