import type { AdminIdentity, AuthConfig } from "./AuthGate";

import type {
  AuditPage,
  DomainSummary,
  Report,
  HistoryVisit,
  Overview,
  User,
  UserSummary,
} from "./types";

import { browserTimezone } from "./time";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function request<T>(
  path: string,
  token: string,
  params?: URLSearchParams,
  asBlob = false,
  signal?: AbortSignal,
  body?: unknown,
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    params.forEach((value, key) => url.searchParams.set(key, value));
  }

  const response = await fetch(url, {
    signal,
    method: body === undefined ? "GET" : "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(token
        ? token.startsWith("google:")
          ? { Authorization: `Bearer ${token.slice(7)}` }
          : {
              "X-Admin-Token": token.startsWith("dev:")
                ? token.slice(4)
                : token,
            }
        : {}),
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : Array.isArray(body?.detail)
          ? body.detail.map((item: { msg: string }) => item.msg).join("; ")
          : response.statusText;
    if (token && (response.status === 401 || response.status === 403)) {
      window.dispatchEvent(
        new CustomEvent("admin-auth-required", {
          detail: { token, message: detail },
        }),
      );
    }
    throw new Error(`${response.status} ${detail}`);
  }

  return (asBlob ? response.blob() : response.json()) as Promise<T>;
}

export const api = {
  revokeDevice: (token: string, id: string) =>
    request<{ revoked: boolean }>(
      `/api/v1/enrollment/${encodeURIComponent(id)}/revoke`,
      token,
      undefined,
      false,
      undefined,
      {},
    ),
  settings: (token: string) =>
    request<import("./SettingsPage").CollectionSettings>(
      "/api/v1/settings",
      token,
    ),
  saveSettings: (
    token: string,
    body: import("./SettingsPage").CollectionSettings,
  ) =>
    request<import("./SettingsPage").CollectionSettings>(
      "/api/v1/settings",
      token,
      undefined,
      false,
      undefined,
      body,
    ),
  deviceHealth: (token: string, params: URLSearchParams) =>
    request<import("./SettingsPage").DeviceHealthPage>(
      "/api/v1/settings/devices",
      token,
      params,
    ),
  activity: (token: string, params: URLSearchParams) =>
    request<import("./TimeSpentPage").ActivitySummary>(
      "/api/v1/activity/summary",
      token,
      params,
    ),
  audit: (token: string, params: URLSearchParams) =>
    request<AuditPage>("/api/v1/audit", token, params),
  authConfig: () => request<AuthConfig>("/api/v1/auth/config", ""),
  me: (token: string) => request<AdminIdentity>("/api/v1/auth/me", token),
  report: (token: string, params: URLSearchParams) =>
    request<Report>("/api/v1/reports", token, params),
  exportReport: (
    token: string,
    params: URLSearchParams,
    signal?: AbortSignal,
  ) => request<Blob>("/api/v1/reports/export.csv", token, params, true, signal),
  overview: (token: string) =>
    request<Overview>(
      "/api/v1/overview",
      token,
      new URLSearchParams({ timezone: browserTimezone() }),
    ),
  users: (token: string) => request<User[]>("/api/v1/users", token),
  userSummaries: (token: string, params: URLSearchParams) =>
    request<UserSummary[]>("/api/v1/users/summary", token, params),
  user: (token: string, id: string) =>
    request<UserSummary>(`/api/v1/users/${encodeURIComponent(id)}`, token),
  domains: (token: string, params: URLSearchParams) =>
    request<DomainSummary[]>("/api/v1/domains", token, params),
  history: (
    token: string,
    filters: {
      userId?: string;
      domain?: string;
      exactDomain?: string;
      offset?: string;
      q?: string;
      start?: string;
      end?: string;
      limit?: string;
    },
  ) => {
    const params = new URLSearchParams();
    if (filters.userId) params.set("user_id", filters.userId);
    if (filters.exactDomain !== undefined)
      params.set("exact_domain", filters.exactDomain);
    if (filters.offset) params.set("offset", filters.offset);
    if (filters.domain) params.set("domain", filters.domain);
    if (filters.q) params.set("q", filters.q);
    if (filters.start)
      params.set("start", new Date(filters.start).toISOString());
    if (filters.end) params.set("end", new Date(filters.end).toISOString());
    params.set("limit", filters.limit ?? "250");
    return request<HistoryVisit[]>("/api/v1/history", token, params);
  },
};
