import type { CaseReport } from "../api";

interface Props {
  report: CaseReport | null;
  loading: boolean;
  queued: boolean;
  onQueue: () => void;
}

export function CasePanel({ report, loading, queued, onQueue }: Props) {
  if (loading) return <div className="case loading">Investigating…</div>;
  if (!report) return <div className="case empty">Select an alert to open its case.</div>;

  const canEnqueue = report.disposition === "ban" || report.disposition === "shadow";
  return (
    <div className="case">
      <div className="case-head">
        <h2>{report.title}</h2>
        <span className={`disp ${report.disposition}`}>{report.disposition}</span>
      </div>
      <div className="case-meta">
        <span>{report.name} · cn {report.cn}</span>
        <span>{report.category}</span>
        <span className="conf">{Math.round(report.confidence * 100)}% confidence</span>
      </div>
      <p className="summary">{report.summary}</p>

      <h3>Evidence</h3>
      <ul className="evidence">
        {report.evidence.map((e, i) => <li key={i}>{e}</li>)}
      </ul>

      {report.likely_types && report.likely_types.length > 0 && (
        <>
          <h3>Likely cheat type</h3>
          <div className="types">
            {report.likely_types.map((t, i) => (
              <span key={t} className={i === 0 ? "type top" : "type"}>{t.replace(/_/g, " ")}</span>
            ))}
          </div>
        </>
      )}

      {report.skill_check && (
        <>
          <h3>Skill or cheat?</h3>
          <p className="skill">{report.skill_check}</p>
        </>
      )}

      {report.review_focus && report.review_focus.length > 0 && (
        <>
          <h3>Check by hand</h3>
          <ul className="focus">
            {report.review_focus.map((x, i) => <li key={i}>{x}</li>)}
          </ul>
        </>
      )}

      <h3>Recommendation</h3>
      <p className="reco">{report.recommendation}</p>

      <div className="case-actions">
        <button
          className="enqueue"
          disabled={!canEnqueue || queued}
          onClick={onQueue}
        >
          {queued ? "Queued for ban wave ✓"
                  : canEnqueue ? "Queue for ban wave"
                  : "Not eligible (monitor/clear)"}
        </button>
        <small>A human approves every ban — this only adds to the next wave.</small>
      </div>
    </div>
  );
}
