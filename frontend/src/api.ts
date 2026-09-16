import type { AdminIdentity, AuthConfig } from "./AuthGate";

import type {
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
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    params.forEach((value, key) => url.searchParams.set(key, value));
  }

  const response = await fetch(url, {
    signal,
    headers: token
      ? token.startsWith("google:")
        ? { Authorization: `Bearer ${token.slice(7)}` }
        : { "X-Admin-Token": token.startsWith("dev:") ? token.slice(4) : token }
      : {},
  });

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const detail =
      typeof body?.detail === "string" ? body.detail : response.statusText;
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
