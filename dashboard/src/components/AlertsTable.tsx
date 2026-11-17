import type { Alert } from "../api";

interface Props {
  alerts: Alert[];
  selected: { match_id: string; cn: number } | null;
  onSelect: (a: Alert) => void;
}

export function AlertsTable({ alerts, selected, onSelect }: Props) {
  return (
    <div className="alerts">
      <h2>Alert queue <span className="count">{alerts.length}</span></h2>
      <div className="alert-list">
        {alerts.map((a) => {
          const active = selected?.match_id === a.match_id && selected?.cn === a.cn;
          return (
            <button
              key={`${a.match_id}:${a.cn}`}
              className={`alert-row ${active ? "active" : ""}`}
              onClick={() => onSelect(a)}
            >
              <span className={`prio ${a.priority}`}>{a.priority}</span>
              <span className="who">
                <strong>{a.name}</strong>
                <small>{a.match_id}</small>
              </span>
              <span className="cat">{a.category ?? "—"}</span>
              <span className="risk">
                <span className="risk-bar" style={{ width: `${a.suspicion * 100}%` }} />
                <span className="risk-num">{Math.round(a.suspicion * 100)}</span>
              </span>
              {a.queued_for_ban && <span className="queued-tag">queued</span>}
            </button>
          );
        })}
        {alerts.length === 0 && <p className="empty">No active alerts.</p>}
      </div>
    </div>
  );
}
