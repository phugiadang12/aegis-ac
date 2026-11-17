import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Alert, BanSnapshot, CaseReport, Replay } from "./api";
import { AlertsTable } from "./components/AlertsTable";
import { CasePanel } from "./components/CasePanel";
import { BanWavePanel } from "./components/BanWavePanel";
import { ReplayViewer } from "./components/ReplayViewer";

export function App() {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [banwave, setBanwave] = useState<BanSnapshot | null>(null);
  const [selected, setSelected] = useState<Alert | null>(null);
  const [report, setReport] = useState<CaseReport | null>(null);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [loadingCase, setLoadingCase] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [a, b] = await Promise.all([api.alerts(), api.banwave()]);
      setAlerts(a);
      setBanwave(b);
      return a;
    } catch (e) {
      setError(String(e));
      return [];
    }
  }, []);

  useEffect(() => {
    refresh().then((a) => { if (a.length) select(a[0]); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const select = useCallback(async (a: Alert) => {
    setSelected(a);
    setLoadingCase(true);
    setReport(null);
    try {
      const [c, r] = await Promise.all([
        api.case(a.match_id, a.cn),
        api.replay(a.match_id),
      ]);
      setReport(c);
      setReplay(r);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoadingCase(false);
    }
  }, []);

  const queueBan = useCallback(async () => {
    if (!selected) return;
    const snap = await api.queueBan(selected.match_id, selected.cn);
    setBanwave(snap);
    await refresh();
  }, [selected, refresh]);

  const releaseWave = useCallback(async () => {
    const snap = await api.releaseWave();
    setBanwave(snap);
    await refresh();
  }, [refresh]);

  const queued = !!selected && !!banwave?.queued.some(
    (r) => r.match_id === selected.match_id && r.cn === selected.cn
  );

  return (
    <div className="app">
      <header>
        <h1>Aegis AC <span className="sub">SOC dashboard</span></h1>
        <p>Server-side behavioural anti-cheat — live alerts, case investigation, 2D replay, ban waves.</p>
      </header>

      {error && <div className="error">API error: {error}. Is the analysis API running on :8008?</div>}

      <div className="grid">
        <aside className="col-alerts">
          <AlertsTable
            alerts={alerts}
            selected={selected ? { match_id: selected.match_id, cn: selected.cn } : null}
            onSelect={select}
          />
          <BanWavePanel snapshot={banwave} onRelease={releaseWave} />
        </aside>

        <main className="col-main">
          {replay ? (
            <ReplayViewer replay={replay} suspectCn={selected?.cn ?? null} />
          ) : (
            <div className="replay empty">Select an alert to load its replay.</div>
          )}
        </main>

        <section className="col-case">
          <CasePanel report={report} loading={loadingCase} queued={queued} onQueue={queueBan} />
        </section>
      </div>
    </div>
  );
}
