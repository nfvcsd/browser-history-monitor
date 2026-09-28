import { FormEvent, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "./api";
import { ActivityPanel } from "./TimeSpentPage";
import { browserTimezone, localDate } from "./time";
import type { Report, User } from "./types";

const number = (n: number) => new Intl.NumberFormat().format(n);
function Activity({
  title,
  entries,
}: {
  title: string;
  entries: { label: string; visits: number }[];
}) {
  const max = Math.max(1, ...entries.map((entry) => entry.visits));
  return (
    <section className="panel">
      <h2>{title}</h2>
      <div className="activity-list" tabIndex={0} aria-label={title}>
        {entries.map((entry) => (
          <div className="activity-row" key={entry.label}>
            <span>{entry.label}</span>
            <div className="activity-track" aria-hidden="true">
              <div style={{ width: `${(entry.visits / max) * 100}%` }} />
            </div>
            <strong>{number(entry.visits)}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function ReportsPage({
  token,
  revision,
}: {
  token: string;
  revision: number;
}) {
  const [params, setParams] = useSearchParams();
  const timeZone = browserTimezone();
  const [defaults] = useState(() => {
    const end = new Date();
    const start = new Date(end);
    start.setDate(start.getDate() - 6);
    return {
      start: localDate(start),
      end: localDate(end),
    };
  });
  const query = new URLSearchParams({
    timezone: timeZone,
    start: params.get("start") ?? defaults.start,
    end: params.get("end") ?? defaults.end,
  });
  for (const key of ["user_id", "domain"]) {
    if (params.get(key)) query.set(key, params.get(key)!);
  }
  const queryKey = query.toString();
  const [users, setUsers] = useState<User[]>([]);
  const [data, setData] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [exportError, setExportError] = useState("");
  const [exporting, setExporting] = useState(false);
  const exportController = useRef<AbortController | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setData(null);
    setExportError("");
    setExporting(false);
    Promise.all([
      api.report(token, new URLSearchParams(queryKey)),
      api.users(token),
    ])
      .then(([report, userData]) => {
        if (active) {
          setData(report);
          setUsers(userData);
        }
      })
      .catch((e) => {
        if (active) setError(e.message || "Unable to load report");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      exportController.current?.abort();
    };
  }, [token, revision, queryKey]);

  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const next = new URLSearchParams();
    for (const key of ["start", "end", "user_id", "domain"]) {
      const value = String(form.get(key) ?? "").trim();
      if (value) next.set(key, value);
    }
    setParams(next);
  }
  async function download() {
    const controller = new AbortController();
    exportController.current?.abort();
    exportController.current = controller;
    setExporting(true);
    setExportError("");
    try {
      const blob = await api.exportReport(
        token,
        new URLSearchParams(queryKey),
        controller.signal,
      );
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `history-${query.get("start")}-${query.get("end")}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      if (!controller.signal.aborted)
        setExportError(e instanceof Error ? e.message : "Export failed");
    } finally {
      if (!controller.signal.aborted) setExporting(false);
    }
  }
  const activityFilters = new URLSearchParams();
  if (data) {
    activityFilters.set("start", new Date(`${data.start}T00:00:00`).toISOString());
    const end = new Date(`${data.end}T00:00:00`); end.setDate(end.getDate() + 1);
    activityFilters.set("end", end.toISOString());
    for (const key of ["user_id", "domain"]) { if (query.get(key)) activityFilters.set(key, query.get(key)!); }
  }
  return (
    <>
      <section className="panel">
        <h2>Reports</h2>
        <p className="muted">
          Choose up to 366 days. Dates and activity use your browser timezone ({timeZone}); both selected dates
          are included. Domain search includes matching subdomains.
        </p>
        <form
          key={queryKey}
          className="filters report-filters"
          onSubmit={apply}
        >
          <label>
            From (local date)
            <input
              type="date"
              name="start"
              defaultValue={query.get("start")!}
              required
            />
          </label>
          <label>
            Through (local date)
            <input
              type="date"
              name="end"
              defaultValue={query.get("end")!}
              required
            />
          </label>
          <label>
            User
            <select
              key={users.length}
              aria-label="User"
              name="user_id"
              defaultValue={query.get("user_id") || ""}
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
            <input
              name="domain"
              defaultValue={query.get("domain") || ""}
              placeholder="e.g. example.com"
              maxLength={512}
            />
          </label>
          <button>Generate report</button>
        </form>
        {loading && <p role="status">Loading report…</p>}
        {error && (
          <div className="error" role="alert">
            {error}. Adjust the filters or refresh to retry.
          </div>
        )}
      </section>
      {data && (
        <>
          <ActivityPanel key={activityFilters.toString()} token={token} revision={revision} filters={activityFilters} />
          <section className="stats">
            {[
              ["Visits", data.visits],
              ["Active users", data.users],
              ["Active devices", data.devices],
              ["Domains", data.domains],
            ].map(([label, value]) => (
              <article key={label}>
                <span>{label}</span>
                <strong>{number(Number(value))}</strong>
              </article>
            ))}
          </section>
          <section className="panel report-export">
            <div>
              <h2>
                {data.start} through {data.end} ({data.timezone})
              </h2>
              <p className="muted">
                {query.get("user_id")
                  ? users.find((user) => user.id === query.get("user_id"))
                      ?.email || "Selected user"
                  : "All users"}{" "}
                ·{" "}
                {query.get("domain")
                  ? `Domains containing “${query.get("domain")}”`
                  : "All domains"}
              </p>
              <p className="muted">
                Export all {number(data.visits)} matching visit rows. Apply
                edited filters before exporting.
              </p>
            </div>
            <button
              className="secondary"
              disabled={exporting}
              onClick={() => void download()}
            >
              {exporting ? "Exporting…" : "Export CSV"}
            </button>
          </section>
          {exportError && (
            <div role="alert" className="error">
              Export failed: {exportError}. Try again.
            </div>
          )}
          {exporting && <p role="status">Preparing CSV…</p>}
          {!data.visits && (
            <p className="empty">No visits match this report’s filters.</p>
          )}
          <section className="panel report-top">
            <h2>Top pages</h2>
            <p className="muted">Up to 20 page title and URL combinations by visit count, using the selected filters. A page whose title changed may appear more than once.</p>
            <div className="table-scroll">
              <table>
                <thead><tr><th>Page title / URL</th><th>Visits</th><th>Unique users</th></tr></thead>
                <tbody>{data.top_pages.map((page) => (
                  <tr key={JSON.stringify([page.url, page.title])}>
                    <td className="report-page"><strong>{page.title || "Untitled page"}</strong>
                      {/^https?:\/\//i.test(page.url) ? <a href={page.url} target="_blank" rel="noreferrer">{page.url}</a> : <span>{page.url}</span>}
                    </td>
                    <td>{number(page.visit_count)}</td><td>{number(page.unique_users)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            {!data.top_pages.length && <p className="empty">No pages in this report.</p>}
          </section>
          <section className="panel report-top">
            <h2>Top domains</h2>
            <p className="muted">
              Up to 20 domains by visit count. Visits without a hostname count
              in totals but are excluded here.
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Domain</th>
                    <th>Visits</th>
                    <th>Unique users</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_domains.map((domain) => (
                    <tr key={domain.domain}>
                      <td>{domain.domain}</td>
                      <td>{number(domain.visit_count)}</td>
                      <td>{number(domain.unique_users)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!data.top_domains.length && (
              <p className="empty">No domains in this report.</p>
            )}
          </section>
          <div className="report-activity">
            <Activity
              title={`Visits by day (${data.timezone})`}
              entries={data.daily.map((day) => ({
                label: day.date,
                visits: day.visits,
              }))}
            />
            <Activity
              title={`Visits by hour (${data.timezone})`}
              entries={data.hourly.map((hour) => ({
                label: `${String(hour.hour).padStart(2, "0")}:00`,
                visits: hour.visits,
              }))}
            />
          </div>
        </>
      )}
    </>
  );
}
