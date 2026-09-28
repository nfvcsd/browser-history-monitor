import { FormEvent, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "./api";
import { localDate } from "./time";
const localInput = (value: string | null) => {
  if (!value) return "";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? ""
    : `${localDate(d)}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
};
import type { User } from "./types";

export function duration(seconds: number) {
  const value = Math.floor(seconds);
  if (value < 60) return `${value}s`;
  if (value < 3600) return `${Math.floor(value / 60)}m ${value % 60}s`;
  return `${Math.floor(value / 3600)}h ${Math.floor((value % 3600) / 60)}m`;
}
export interface ActivitySummary {
  active_seconds: number;
  samples: number;
  users: number;
  first_activity: string | null;
  has_more: boolean;
  items: {
    key: string;
    title: string | null;
    active_seconds: number;
    users: number;
    user_id: string;
  }[];
}
export function ActivityPanel({
  token,
  revision,
  filters,
}: {
  token: string;
  revision: number;
  filters: URLSearchParams;
}) {
  const [group, setGroup] = useState("page");
  const [offset, setOffset] = useState(0);
  const [state, setState] = useState<{
    data?: ActivitySummary;
    error?: string;
  }>({});
  const key = filters.toString();
  useEffect(() => {
    setOffset(0);
  }, [key]);
  useEffect(() => {
    let active = true;
    setState({});
    const query = new URLSearchParams(key);
    query.set("group_by", group);
    query.set("offset", String(offset));
    api
      .activity(token, query)
      .then((data) => {
        if (active) setState({ data });
      })
      .catch((e) => {
        if (active) setState({ error: e.message });
      });
    return () => {
      active = false;
    };
  }, [token, revision, key, group, offset]);
  return (
    <section className="panel time-panel">
      <h2>Time spent</h2>
      <p className="muted">
        Measured active time in the focused browser tab. Pauses after 60 seconds
        of system inactivity. Historical visits have no inferred duration;
        missing samples do not mean no browsing. Totals combine time across
        devices.
      </p>
      <div className="time-tabs" aria-label="Time grouping">
        {[
          ["page", "Pages"],
          ["domain", "Domains"],
          ["user", "Users"],
        ].map(([value, label]) => (
          <button
            type="button"
            aria-pressed={group === value}
            className={group === value ? "" : "secondary"}
            key={value}
            onClick={() => {
              setGroup(value);
              setOffset(0);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {state.error ? (
        <p className="error" role="alert">
          {state.error}
        </p>
      ) : !state.data ? (
        <p role="status">Loading time measurements…</p>
      ) : (
        <>
          <p>
            <strong>{duration(state.data.active_seconds)}</strong> recorded ·{" "}
            {state.data.users} users
            {state.data.first_activity && (
              <>
                {" "}
                · first matching sample{" "}
                {new Date(state.data.first_activity).toLocaleString()}
              </>
            )}
          </p>
          {!state.data.samples && (
            <p className="empty">
              No measured time for these filters. Time is collected only after
              the updated extension is installed.
            </p>
          )}
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>
                    {group === "page"
                      ? "Page title / URL"
                      : group === "domain"
                        ? "Domain"
                        : "User"}
                  </th>
                  <th>Active time</th>
                  {group !== "user" && <th>Users</th>}
                </tr>
              </thead>
              <tbody>
                {state.data.items.map((item) => (
                  <tr key={item.key}>
                    <td className="report-page">
                      {group === "page" ? (
                        <>
                          <strong>{item.title || "Untitled page"}</strong>
                          <a href={item.key} target="_blank" rel="noreferrer">
                            {item.key}
                          </a>
                        </>
                      ) : group === "user" ? (
                        <Link
                          to={`/time?${new URLSearchParams({ ...Object.fromEntries(filters), user_id: item.user_id })}`}
                        >
                          {item.key}
                        </Link>
                      ) : (
                        item.key
                      )}
                    </td>
                    <td>{duration(item.active_seconds)}</td>
                    {group !== "user" && <td>{item.users}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="pagination">
            <button
              className="secondary"
              disabled={!offset}
              onClick={() => setOffset((value) => Math.max(0, value - 100))}
            >
              Previous
            </button>
            <span>{state.data.items.length} rows shown</span>
            <button
              className="secondary"
              disabled={!state.data.has_more}
              onClick={() => setOffset((value) => value + 100)}
            >
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}
export default function TimeSpentPage({
  token,
  revision,
}: {
  token: string;
  revision: number;
}) {
  const [params, setParams] = useSearchParams();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    api
      .users(token)
      .then((data) => {
        if (active) setUsers(data);
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [token, revision]);
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = new URLSearchParams();
    new FormData(event.currentTarget).forEach((value, key) => {
      if (String(value).trim()) next.set(key, String(value).trim());
    });
    setParams(next);
  }
  const filters = new URLSearchParams();
  let filterError = "";
  try {
    for (const key of ["user_id", "domain", "q", "start", "end"]) {
      const value = params.get(key);
      if (value)
        filters.set(
          key,
          ["start", "end"].includes(key)
            ? new Date(value).toISOString()
            : value,
        );
    }
  } catch {
    filterError = "Invalid time filter. Please choose valid dates.";
  }
  return (
    <>
      <section className="panel">
        <h2>Browsing time</h2>
        <p className="muted">
          All recorded time by default. Choose a user for individual page and
          domain totals. Date filters use your local timezone.
        </p>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
        <form
          key={params.toString()}
          className="filters report-filters"
          onSubmit={apply}
        >
          <label>
            User
            <select
              key={users.length}
              aria-label="User"
              name="user_id"
              defaultValue={params.get("user_id") || ""}
            >
              <option value="">All users</option>
              {users.map((user) => (
                <option key={user.id} value={user.id}>
                  {user.email}
                </option>
              ))}
            </select>
          </label>
          <label>
            Domain contains
            <input name="domain" defaultValue={params.get("domain") || ""} />
          </label>
          <label>
            Search pages
            <input
              name="q"
              defaultValue={params.get("q") || ""}
              placeholder="Title, URL or user email"
            />
          </label>
          <label>
            From (local time)
            <input
              type="datetime-local"
              name="start"
              defaultValue={localInput(params.get("start"))}
            />
          </label>
          <label>
            Through (local time)
            <input
              type="datetime-local"
              name="end"
              defaultValue={localInput(params.get("end"))}
            />
          </label>
          <button>Apply filters</button>
        </form>
      </section>
      {filterError ? (
        <p role="alert" className="error">
          {filterError}
        </p>
      ) : (
        <ActivityPanel
          key={filters.toString()}
          token={token}
          revision={revision}
          filters={filters}
        />
      )}
    </>
  );
}
