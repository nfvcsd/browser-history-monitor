import type { HistoryVisit, Overview, User } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

async function request<T>(
  path: string,
  token: string,
  params?: URLSearchParams,
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`);
  if (params) {
    params.forEach((value, key) => url.searchParams.set(key, value));
  }

  const response = await fetch(url, {
    headers: {
      "X-Admin-Token": token,
    },
  });

  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export const api = {
  overview: (token: string) => request<Overview>("/api/v1/overview", token),
  users: (token: string) => request<User[]>("/api/v1/users", token),
  history: (
    token: string,
    filters: {
      userId?: string;
      domain?: string;
      q?: string;
      start?: string;
      end?: string;
      limit?: string;
    },
  ) => {
    const params = new URLSearchParams();
    if (filters.userId) params.set("user_id", filters.userId);
    if (filters.domain) params.set("domain", filters.domain);
    if (filters.q) params.set("q", filters.q);
    if (filters.start) params.set("start", new Date(filters.start).toISOString());
    if (filters.end) params.set("end", new Date(filters.end).toISOString());
    params.set("limit", filters.limit ?? "250");
    return request<HistoryVisit[]>("/api/v1/history", token, params);
  },
};
