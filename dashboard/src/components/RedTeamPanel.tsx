import { useState } from "react";

const PROFILES = [
  { id: "aimbot", label: "Aimbot" },
  { id: "humanised", label: "Humanised aimbot" },
  { id: "triggerbot", label: "Triggerbot" },
  { id: "esp", label: "ESP / wallhack" },
];

interface Props {
  onInject: (profile: string, escalate: boolean) => Promise<void>;
}

export function RedTeamPanel({ onInject }: Props) {
  const [profile, setProfile] = useState("aimbot");
  const [escalate, setEscalate] = useState(false);
  const [busy, setBusy] = useState(false);

  async function go() {
    setBusy(true);
    try { await onInject(profile, escalate); } finally { setBusy(false); }
  }

  return (
    <div className="redteam">
      <h2>Red team <span className="tag-demo">demo</span></h2>
      <p className="rt-note">
        Inject a synthetic cheater — streams the cheat's telemetry signature, never a real hack —
        and watch it get caught live.
      </p>
      <div className="rt-row">
        <select value={profile} onChange={(e) => setProfile(e.target.value)} disabled={busy}>
          {PROFILES.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
        <button className="inject" onClick={go} disabled={busy}>
          {busy ? "Injecting…" : "Inject cheater"}
        </button>
      </div>
      <label className="rt-check">
        <input type="checkbox" checked={escalate}
               onChange={(e) => setEscalate(e.target.checked)} disabled={busy} />
        Auto-escalate to Discord
      </label>
    </div>
  );
}
