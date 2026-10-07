import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "./api";

export interface CollectionSettings {
  revision: number;
  retention_days: number | null;
  stale_minutes: number;
  timezone: string;
  schedule_enabled: boolean;
  days: { enabled: boolean; start: string; end: string }[];
  ip_enabled: boolean;
  ip_source: "connection" | "device";
  public_ips: string[];
}
export interface DeviceHealthPage {
  items: {
    id: string;
    email: string;
    device_name: string | null;
    extension_version: string | null;
    last_sync_at: string | null;
    last_check_in: string | null;
    source_ip: string | null;
    status: string;
    policy_revision: number | null;
    enrollment_status: "legacy" | "verified" | "expired" | "revoked";
    verified_at: string | null;
    credential_expires_at: string | null;
  }[];
  has_more: boolean;
}
const weekdays = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];
const statuses: Record<string, string> = {
  revoked: "Revoked by administrator",
  collecting: "Ready to collect",
  outside_schedule: "Paused: outside schedule",
  ip_not_allowed: "Paused: IP not allowed",
  public_ip_unavailable: "Paused: public IP unavailable",
  not_reporting: "Not reporting",
  upgrade_required: "No check-in: update extension",
};
const time = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "Never";

export default function SettingsPage({
  token,
  revision,
}: {
  token: string;
  revision: number;
}) {
  const [revokeId, setRevokeId] = useState<string>();
  const [revoking, setRevoking] = useState(false);
  const [settings, setSettings] = useState<CollectionSettings>();
  const [addresses, setAddresses] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [health, setHealth] = useState<DeviceHealthPage>();
  const [healthError, setHealthError] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    api
      .settings(token)
      .then((data) => {
        if (active) {
          setSettings(data);
          setAddresses(data.public_ips.join("\n"));
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [token, reload]);
  useEffect(() => {
    let active = true;
    setHealth(undefined);
    setHealthError("");
    api
      .deviceHealth(token, new URLSearchParams({ q, offset: String(offset) }))
      .then((data) => {
        if (active) setHealth(data);
      })
      .catch((e) => {
        if (active) setHealthError(e.message);
      });
    return () => {
      active = false;
    };
  }, [token, revision, reload, q, offset]);
  async function revoke(id: string) {
    setRevoking(true);
    try {
      await api.revokeDevice(token, id);
      setHealth((h) =>
        h
          ? {
              ...h,
              items: h.items.map((d) =>
                d.id === id
                  ? { ...d, enrollment_status: "revoked", status: "revoked" }
                  : d,
              ),
            }
          : h,
      );
      setRevokeId(undefined);
    } catch (e) {
      setHealthError((e as Error).message);
    } finally {
      setRevoking(false);
    }
  }
  function change(values: Partial<CollectionSettings>) {
    setSettings((s) => (s ? { ...s, ...values } : s));
    setMessage("");
  }
  async function save(event: FormEvent) {
    event.preventDefault();
    if (!settings) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const saved = await api.saveSettings(token, {
        ...settings,
        public_ips: addresses
          .split(/[\n,]+/)
          .map((s) => s.trim())
          .filter(Boolean),
      });
      setSettings(saved);
      setAddresses(saved.public_ips.join("\n"));
      setMessage(
        "Settings saved. Devices receive changes at their next policy check (normally within 30 seconds).",
      );
      setReload((v) => v + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <section className="panel">
        <h2>Collection settings</h2>
        <p>
          These rules apply to all users and devices in this deployment, for
          both history and time measurements.
        </p>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        {message && <p role="status">{message}</p>}
        {!settings ? (
          <button onClick={() => setReload((v) => v + 1)}>Load settings</button>
        ) : (
          <form onSubmit={save} className="settings-form">
            <fieldset disabled={busy}>
              <legend>Retention and device health</legend>
              <label>
                Keep browsing data for (days)
                <input
                  type="number"
                  min="1"
                  max="3650"
                  value={settings.retention_days ?? ""}
                  placeholder="Keep indefinitely"
                  onChange={(e) =>
                    change({
                      retention_days: e.target.value
                        ? Number(e.target.value)
                        : null,
                    })
                  }
                />
              </label>
              <p className="muted">
                Leave blank to keep data indefinitely. Saving a number enables
                permanent deletion of older history and time measurements.
                Cleanup runs every five minutes in batches; larger backlogs take
                longer. Audit records, users and devices are retained.
              </p>
              <label>
                Flag devices after no check-in for (minutes)
                <input
                  type="number"
                  min="2"
                  max="10080"
                  required
                  value={settings.stale_minutes}
                  onChange={(e) =>
                    change({ stale_minutes: Number(e.target.value) })
                  }
                />
              </label>
            </fieldset>
            <fieldset disabled={busy}>
              <legend>Weekly collection schedule</legend>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={settings.schedule_enabled}
                  onChange={(e) =>
                    change({ schedule_enabled: e.target.checked })
                  }
                />
                Only collect during scheduled hours
              </label>
              <label>
                School timezone
                <input
                  required
                  value={settings.timezone}
                  onChange={(e) => change({ timezone: e.target.value })}
                  placeholder="America/Chicago"
                />
              </label>
              <p className="muted">
                Uses this school timezone, including daylight saving time,
                regardless of the device timezone. An end time earlier than the
                start continues into the next day. Unchecked days have no window
                starting that day. If no days are checked, scheduled collection
                is paused all week.
              </p>
              <div className="schedule-days">
                {settings.days.map((day, index) => (
                  <div className="schedule-day" key={weekdays[index]}>
                    <label className="check-label">
                      <input
                        type="checkbox"
                        disabled={!settings.schedule_enabled}
                        checked={day.enabled}
                        onChange={(e) =>
                          change({
                            days: settings.days.map((d, i) =>
                              i === index
                                ? { ...d, enabled: e.target.checked }
                                : d,
                            ),
                          })
                        }
                      />
                      {weekdays[index]}
                    </label>
                    <label>
                      Start
                      <input
                        aria-label={`${weekdays[index]} start`}
                        type="time"
                        required
                        disabled={!settings.schedule_enabled || !day.enabled}
                        value={day.start}
                        onChange={(e) =>
                          change({
                            days: settings.days.map((d, i) =>
                              i === index ? { ...d, start: e.target.value } : d,
                            ),
                          })
                        }
                      />
                    </label>
                    <label>
                      End
                      <input
                        aria-label={`${weekdays[index]} end`}
                        type="time"
                        required
                        disabled={!settings.schedule_enabled || !day.enabled}
                        value={day.end}
                        onChange={(e) =>
                          change({
                            days: settings.days.map((d, i) =>
                              i === index ? { ...d, end: e.target.value } : d,
                            ),
                          })
                        }
                      />
                    </label>
                  </div>
                ))}
              </div>
            </fieldset>
            <fieldset disabled={busy}>
              <legend>Allowed public IP addresses</legend>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={settings.ip_enabled}
                  onChange={(e) => change({ ip_enabled: e.target.checked })}
                />
                Only collect from listed public IP addresses
              </label>
              <label>
                How to determine the public IP
                <select
                  aria-label="How to determine the public IP"
                  value={settings.ip_source}
                  onChange={(e) =>
                    change({
                      ip_source: e.target
                        .value as CollectionSettings["ip_source"],
                    })
                  }
                >
                  <option value="connection">
                    Backend connection (public server / trusted proxy)
                  </option>
                  <option value="device">
                    Device lookup (localhost / school LAN)
                  </option>
                </select>
              </label>
              <p className="muted">
                Connection mode checks the address seen by the backend. Device
                lookup contacts ipify over HTTPS and reports its result; it
                sends no browsing data or credentials to ipify, but relies on
                the managed extension reporting honestly. A failed lookup pauses
                collection.
              </p>
              <label>
                Public IPv4 or IPv6 addresses, one per line
                <textarea
                  aria-label="Public IPv4 or IPv6 addresses, one per line"
                  rows={5}
                  value={addresses}
                  onChange={(e) => {
                    setAddresses(e.target.value);
                    setMessage("");
                  }}
                  placeholder="Enter your school's public addresses"
                />
              </label>
              <p className="muted">
                Individual public addresses only, not private LAN addresses or
                address ranges. An enabled, empty list blocks all collection.
                Include the IPv4/IPv6 addresses your school uses. Network
                changes are checked periodically; detection is not
                instantaneous.
              </p>
            </fieldset>
            <p className="muted">
              Schedules and IP restrictions require extension 0.3.0 or newer.
              Restricted collection skips unverified historical backfill and
              pauses when policy checks fail. Saving settings invalidates
              earlier collection permissions, so pending samples may be
              discarded. Health check-ins continue while collection is paused.
            </p>
            <div className="settings-actions">
              <button disabled={busy}>
                {busy ? "Saving…" : "Save settings"}
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => {
                  setReload((v) => v + 1);
                  setMessage("");
                }}
              >
                Reload saved settings
              </button>
            </div>
          </form>
        )}
      </section>
      <section className="panel">
        <h2>Collection health</h2>
        <p className="muted">
          Ready means the device checked in and is allowed to collect; it does
          not prove browsing occurred. Sleeping or closed browsers eventually
          appear as not reporting. Last sync is the last acknowledged
          history/time upload.
        </p>
        <label className="health-search">
          Find user or device
          <input
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setOffset(0);
            }}
          />
        </label>
        {healthError ? (
          <p className="error" role="alert">
            {healthError}
          </p>
        ) : !health ? (
          <p role="status">Loading devices…</p>
        ) : (
          <>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>User / device</th>
                    <th>Status</th>
                    <th>Last check-in</th>
                    <th>Last sync</th>
                    <th>Public / observed IP</th>
                    <th>Extension</th>
                    <th>Enrollment</th>
                  </tr>
                </thead>
                <tbody>
                  {health.items.map((device) => (
                    <tr key={device.id}>
                      <td>
                        {device.email}
                        <div className="muted device-name">
                          {device.device_name || device.id}
                        </div>
                      </td>
                      <td>{statuses[device.status] || device.status}</td>
                      <td>{time(device.last_check_in)}</td>
                      <td>{time(device.last_sync_at)}</td>
                      <td>{device.source_ip || "Unavailable"}</td>
                      <td>{device.extension_version || "Unknown"}</td>
                      <td>
                        <strong>{device.enrollment_status}</strong>
                        {device.verified_at && (
                          <div className="muted">
                            Verified {time(device.verified_at)}
                          </div>
                        )}
                        {["verified", "expired"].includes(
                          device.enrollment_status,
                        ) &&
                          (revokeId === device.id ? (
                            <div>
                              <p>
                                Stop uploads from this enrollment? Automatic
                                renewal will also be blocked.
                              </p>
                              <button
                                disabled={revoking}
                                onClick={() => revoke(device.id)}
                              >
                                Confirm revoke
                              </button>
                              <button
                                className="secondary"
                                disabled={revoking}
                                onClick={() => setRevokeId(undefined)}
                              >
                                Cancel
                              </button>
                            </div>
                          ) : (
                            <button
                              className="secondary"
                              onClick={() => setRevokeId(device.id)}
                            >
                              Revoke enrollment
                            </button>
                          ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!health.items.length && <p>No matching devices have enrolled.</p>}
            <div className="pagination">
              <button
                className="secondary"
                disabled={!offset}
                onClick={() => setOffset((v) => Math.max(0, v - 100))}
              >
                Previous
              </button>
              <span>{health.items.length} devices shown</span>
              <button
                className="secondary"
                disabled={!health.has_more}
                onClick={() => setOffset((v) => v + 100)}
              >
                Next
              </button>
            </div>
          </>
        )}
        <p>
          <Link to="/audit">
            View settings changes and access in the audit log
          </Link>
        </p>
      </section>
    </>
  );
}
