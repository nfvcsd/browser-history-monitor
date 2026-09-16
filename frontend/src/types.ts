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
