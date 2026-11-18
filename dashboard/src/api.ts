// Typed client for the Aegis analysis API (aegis_soc.api).

export interface Alert {
  match_id: string;
  cn: number;
  name: string;
  suspicion: number;
  category: string | null;
  priority: "high" | "medium";
  queued_for_ban: boolean;
}

export interface MatchSummary {
  match_id: string;
  profile: string;
  players: number;
  flagged: number;
  duration_ms: number;
}

export type Disposition = "ban" | "shadow" | "monitor" | "clear";

export interface CaseReport {
  cn: number;
  name: string;
  category: string;
  confidence: number;
  disposition: Disposition;
  title: string;
  summary: string;
  evidence: string[];
  recommendation: string;
  likely_types?: string[];
  skill_check?: string;
  review_focus?: string[];
}

export interface ReplayPlayer {
  cn: number;
  name: string;
  flagged: boolean;
  category: string | null;
  suspicion: number;
}

// Compact row encodings from the API.
// trajectory point: [ts, x, y, yaw, alive]
export type TrajPoint = [number, number, number, number, number];
// shot: [cn, ts, ox, oy, tx, ty]
export type ShotRow = [number, number, number, number, number, number];
// honeypot: [ts, x, y]
export type GhostRow = [number, number, number];

export interface Replay {
  match_id: string;
  map_size: number;
  duration_ms: number;
  players: ReplayPlayer[];
  trajectories: Record<string, TrajPoint[]>;
  shots: ShotRow[];
  honeypot: GhostRow[];
}

export interface BanRecord {
  match_id: string;
  cn: number;
  name: string;
  category: string;
  confidence: number;
  queued_at: number;
  status: "queued" | "banned";
  banned_at: number | null;
}

export interface BanSnapshot {
  queued: BanRecord[];
  history: BanRecord[];
  waves_released: number;
  delay_seconds: number;
  seconds_until_due: number;
  enforcement_log: string[];
}

async function get<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

async function post<T>(url: string): Promise<T> {
  const r = await fetch(url, { method: "POST" });
  if (!r.ok) throw new Error(`${url} → ${r.status}`);
  return r.json() as Promise<T>;
}

export const api = {
  alerts: () => get<Alert[]>("/api/alerts"),
  matches: () => get<MatchSummary[]>("/api/matches"),
  case: (matchId: string, cn: number) =>
    get<CaseReport>(`/api/matches/${matchId}/cases/${cn}`),
  replay: (matchId: string) => get<Replay>(`/api/matches/${matchId}/replay`),
  banwave: () => get<BanSnapshot>("/api/banwave"),
  queueBan: (matchId: string, cn: number) =>
    post<BanSnapshot>(`/api/banwave/queue/${matchId}/${cn}`),
  releaseWave: () => post<BanSnapshot & { released: BanRecord[] }>("/api/banwave/release"),
  inject: (profile: string, escalate: boolean) =>
    post<{ match_id: string; profile: string; alerts: Alert[]; escalated: boolean }>(
      `/api/redteam/inject?profile=${profile}&escalate=${escalate}`),
};
