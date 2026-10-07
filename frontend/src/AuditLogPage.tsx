import { FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "./api";
import { browserTimezone } from "./time";
import type { AuditPage } from "./types";

const actions: Record<string, string> = {
  "device.enroll": "Enroll device",
  "device.renew": "Renew device credential",
  "device.revoke": "Revoke device",
  "settings.view": "View settings",
  "settings.update": "Update settings",
  "devices.health": "View device health",
  "activity.view": "View time spent",
  "overview.view": "View overview",
  "users.list": "List users",
  "user.view": "View user",
  "domains.view": "View domains",
  "history.view": "View history",
  "history.search": "Search history",
  "reports.generate": "Generate report",
  "export.requested": "Export requested",
  "audit.view": "View audit log",
};
const filterLabels: Record<string, string> = {
  user_id: "User ID",
  domain: "Domain contains",
  exact_domain: "Exact domain",
  q: "Search",
  start: "From",
  end: "Through",
  timezone: "Timezone",
  limit: "Page size",
  offset: "Offset",
  before_id: "Before event",
  actor: "Administrator search",
  action: "Action",
  values_truncated: "Long filter values shortened",
};
const date = (value: string) =>
  new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));

export default function AuditLogPage({
  token,
  revision,
}: {
  token: string;
  revision: number;
}) {
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<AuditPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const queryKey = params.toString();
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    setData(null);
    const load = async () => {
      const query = new URLSearchParams(queryKey);
      query.set("limit", "100");
      for (const key of ["start", "end"]) {
        if (query.get(key))
          query.set(key, new Date(query.get(key)!).toISOString());
      }
      return api.audit(token, query);
    };
    load()
      .then((result) => {
        if (active) setData(result);
      })
      .catch((e) => {
        if (active) setError(e.message || "Unable to load audit log");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [token, revision, queryKey]);
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const next = new URLSearchParams();
    new FormData(event.currentTarget).forEach((value, key) => {
      if (String(value).trim()) next.set(key, String(value).trim());
    });
    setParams(next);
  }
  function page(before?: number) {
    const next = new URLSearchParams(params);
    if (before) next.set("before_id", String(before));
    else next.delete("before_id");
    setParams(next);
  }
  return (
    <section className="panel">
      <h2>Audit Log</h2>
      <p className="muted">
        Administrator activity, newest first. Times are shown in{" "}
        {browserTimezone()}. Export requested means the server authorized the
        export; it does not confirm the file was saved.
      </p>
      <form key={queryKey} className="filters report-filters" onSubmit={apply}>
        <label>
          Administrator
          <input
            name="actor"
            defaultValue={params.get("actor") || ""}
            placeholder="Email or account ID"
            maxLength={320}
          />
        </label>
        <label>
          Action
          <select
            aria-label="Action"
            name="action"
            defaultValue={params.get("action") || ""}
          >
            <option value="">All actions</option>
            {Object.entries(actions).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label>
          From (local time)
          <input
            type="datetime-local"
            name="start"
            defaultValue={params.get("start") || ""}
          />
        </label>
        <label>
          Through (local time)
          <input
            type="datetime-local"
            name="end"
            defaultValue={params.get("end") || ""}
          />
        </label>
        <button>Apply filters</button>
      </form>
      {loading && <p role="status">Loading audit log…</p>}
      {error && (
        <div role="alert" className="error">
          {error}. Adjust the filters or refresh to retry.
        </div>
      )}
      {data && (
        <>
          <div className="table-scroll">
            <table className="audit-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Administrator</th>
                  <th>Action</th>
                  <th>Result</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((event) => (
                  <tr key={event.id}>
                    <td>{date(event.created_at)}</td>
                    <td>
                      {event.actor_email || "Development administrator"}
                      <div className="muted">
                        {event.actor_mode === "google"
                          ? "Google Workspace"
                          : "Shared development token"}
                      </div>
                    </td>
                    <td>{actions[event.action] || event.action}</td>
                    <td>
                      {event.status_code < 400 ? "Accepted" : "Failed"} (
                      {event.status_code})
                      {event.result_count !== null && (
                        <div className="muted">
                          {event.result_count.toLocaleString()}{" "}
                          {event.action === "reports.generate"
                            ? "matching visits"
                            : "rows returned"}
                        </div>
                      )}
                    </td>
                    <td>
                      <details>
                        <summary>Filters &amp; identity</summary>
                        <dl className="audit-details">
                          <dt>Event ID</dt>
                          <dd>{event.id}</dd>
                          <dt>Account ID</dt>
                          <dd>{event.actor_sub}</dd>
                          {Object.entries(event.filters).map(([key, value]) => (
                            <div key={key}>
                              <dt>{filterLabels[key] || key}</dt>
                              <dd>
                                {typeof value === "object"
                                  ? JSON.stringify(value)
                                  : String(value)}
                              </dd>
                            </div>
                          ))}
                          {!Object.keys(event.filters).length && (
                            <dd>No explicit filters</dd>
                          )}
                        </dl>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!data.items.length && (
            <p className="empty">No audit events match these filters.</p>
          )}
          <div className="pagination">
            <button
              className="secondary"
              disabled={!params.has("before_id")}
              onClick={() => page()}
            >
              Latest events
            </button>
            <span>{data.items.length} events shown</span>
            <button
              className="secondary"
              disabled={data.next_cursor === null}
              onClick={() => page(data.next_cursor!)}
            >
              Older events
            </button>
          </div>
        </>
      )}
    </section>
  );
}
