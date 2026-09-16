export interface Overview {
  users: number;
  devices: number;
  visits: number;
  domains: number;
  visits_today: number;
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  created_at: string;
  last_seen_at: string;
}

export interface HistoryVisit {
  id: number;
  user_id: string;
  user_email: string;
  device_id: string;
  device_name: string | null;
  url: string;
  domain: string;
  title: string | null;
  visit_time: string;
  transition: string | null;
  is_local: boolean | null;
  visit_count: number | null;
  typed_count: number | null;
}

export interface UserSummary extends User {
  last_sync_at: string | null;
  device_count: number;
  visit_count: number;
}

export interface DomainSummary {
  domain: string;
  visit_count: number;
  unique_users: number;
  first_activity: string;
  last_activity: string;
}

export interface Report {
  start: string;
  end: string;
  timezone: string;
  visits: number;
  users: number;
  devices: number;
  domains: number;
  top_pages: { title: string | null; url: string; visit_count: number; unique_users: number }[];
  top_domains: { domain: string; visit_count: number; unique_users: number }[];
  daily: { date: string; visits: number }[];
  hourly: { hour: number; visits: number }[];
}
