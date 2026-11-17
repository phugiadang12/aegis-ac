import type { BanSnapshot } from "../api";

interface Props {
  snapshot: BanSnapshot | null;
  onRelease: () => void;
}

function humanDelay(seconds: number): string {
  if (seconds <= 0) return "due now";
  if (seconds >= 3600) return `${(seconds / 3600).toFixed(1)}h`;
  if (seconds >= 60) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds)}s`;
}

export function BanWavePanel({ snapshot, onRelease }: Props) {
  if (!snapshot) return null;
  const { queued, history, waves_released, seconds_until_due, enforcement_log } = snapshot;
  return (
    <div className="banwave">
      <div className="banwave-head">
        <h2>Ban wave</h2>
        <button className="release" disabled={queued.length === 0} onClick={onRelease}>
          Release wave now
        </button>
      </div>
      <p className="wave-note">
        Confirmed cheaters are banned together, not instantly — so cheat authors
        can't tell which match exposed them. Next auto-release in{" "}
        <strong>{humanDelay(seconds_until_due)}</strong>. Waves released: {waves_released}.
      </p>

      <h3>Queued <span className="count">{queued.length}</span></h3>
      <ul className="ban-list">
        {queued.map((r) => (
          <li key={`${r.match_id}:${r.cn}`}>
            <strong>{r.name}</strong> <span className="cat">{r.category}</span>
            <span className="conf">{Math.round(r.confidence * 100)}%</span>
          </li>
        ))}
        {queued.length === 0 && <li className="empty">Nothing queued.</li>}
      </ul>

      {enforcement_log.length > 0 && (
        <>
          <h3>Enforcement log</h3>
          <pre className="log">{enforcement_log.join("\n")}</pre>
        </>
      )}

      {history.length > 0 && (
        <p className="history-note">{history.length} player(s) banned across all waves.</p>
      )}
    </div>
  );
}
