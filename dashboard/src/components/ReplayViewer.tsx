import { useEffect, useRef, useState } from "react";
import type { Replay, TrajPoint } from "../api";

const SIZE = 560; // canvas px (square)
const PAD = 28;

interface Props {
  replay: Replay;
  suspectCn: number | null;
}

// Last trajectory point at or before time t.
function pointAt(traj: TrajPoint[], t: number): TrajPoint | null {
  let lo = 0;
  let found: TrajPoint | null = null;
  for (; lo < traj.length; lo++) {
    if (traj[lo][0] <= t) found = traj[lo];
    else break;
  }
  return found;
}

export function ReplayViewer({ replay, suspectCn }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(true);
  const raf = useRef<number>(0);
  const last = useRef<number>(0);

  // Reset to the start whenever a different match is loaded.
  useEffect(() => {
    setTime(0);
    setPlaying(true);
  }, [replay.match_id]);

  // Playback clock (4x real time so a 45s match plays in ~11s).
  useEffect(() => {
    if (!playing) return;
    last.current = performance.now();
    const tick = (now: number) => {
      const dt = (now - last.current) * 4;
      last.current = now;
      setTime((t) => (t + dt > replay.duration_ms ? 0 : t + dt));
      raf.current = requestAnimationFrame(tick);
    };
    raf.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf.current);
  }, [playing, replay.duration_ms]);

  // Draw.
  useEffect(() => {
    const ctx = canvasRef.current?.getContext("2d");
    if (!ctx) return;
    const S = replay.map_size;
    const scale = (SIZE - 2 * PAD) / S;
    const X = (x: number) => PAD + x * scale;
    const Y = (y: number) => PAD + (S - y) * scale; // flip so +y is up

    ctx.clearRect(0, 0, SIZE, SIZE);
    // arena
    ctx.fillStyle = "#0e1726";
    ctx.fillRect(0, 0, SIZE, SIZE);
    ctx.strokeStyle = "#24324a";
    ctx.lineWidth = 1;
    for (let g = 0; g <= 4; g++) {
      const p = PAD + ((SIZE - 2 * PAD) / 4) * g;
      ctx.beginPath(); ctx.moveTo(p, PAD); ctx.lineTo(p, SIZE - PAD); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(PAD, p); ctx.lineTo(SIZE - PAD, p); ctx.stroke();
    }

    // recent shots (fading 250ms trail)
    for (const [cn, ts, ox, oy, tx, ty] of replay.shots) {
      const age = time - ts;
      if (age < 0 || age > 250) continue;
      ctx.strokeStyle = cn === suspectCn
        ? `rgba(239,68,68,${1 - age / 250})`
        : `rgba(148,163,184,${0.5 * (1 - age / 250)})`;
      ctx.lineWidth = cn === suspectCn ? 1.5 : 1;
      ctx.beginPath(); ctx.moveTo(X(ox), Y(oy)); ctx.lineTo(X(tx), Y(ty)); ctx.stroke();
    }

    // honeypot phantom (what the wallhack can "see")
    const ghost = pointAtGhost(replay.honeypot, time);
    if (ghost) {
      const pulse = 5 + 2 * Math.sin(time / 120);
      ctx.strokeStyle = "#f59e0b";
      ctx.fillStyle = "rgba(245,158,11,0.18)";
      ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.arc(X(ghost[1]), Y(ghost[2]), pulse, 0, Math.PI * 2);
      ctx.fill(); ctx.stroke();
    }

    // players
    for (const p of replay.players) {
      const traj = replay.trajectories[String(p.cn)];
      if (!traj || traj.length === 0) continue;
      const isSuspect = p.cn === suspectCn;
      const color = isSuspect ? "#ef4444" : p.flagged ? "#f59e0b" : "#38bdf8";

      // path up to now
      ctx.strokeStyle = isSuspect ? "rgba(239,68,68,0.9)" : "rgba(56,189,248,0.25)";
      ctx.lineWidth = isSuspect ? 2 : 1;
      ctx.beginPath();
      let started = false;
      for (const pt of traj) {
        if (pt[0] > time) break;
        const cx = X(pt[1]); const cy = Y(pt[2]);
        if (!started) { ctx.moveTo(cx, cy); started = true; } else ctx.lineTo(cx, cy);
      }
      ctx.stroke();

      const cur = pointAt(traj, time);
      if (!cur) continue;
      const cx = X(cur[1]); const cy = Y(cur[2]);
      // crosshair direction
      const rad = (cur[3] * Math.PI) / 180;
      ctx.strokeStyle = color;
      ctx.lineWidth = isSuspect ? 2 : 1;
      ctx.beginPath();
      ctx.moveTo(cx, cy);
      ctx.lineTo(cx + Math.cos(rad) * (isSuspect ? 22 : 14),
                 cy - Math.sin(rad) * (isSuspect ? 22 : 14));
      ctx.stroke();
      // dot
      ctx.fillStyle = color;
      ctx.beginPath(); ctx.arc(cx, cy, isSuspect ? 6 : 4, 0, Math.PI * 2); ctx.fill();
      if (isSuspect) {
        ctx.fillStyle = "#fecaca";
        ctx.font = "11px system-ui";
        ctx.fillText(p.name, cx + 8, cy - 8);
      }
    }
  }, [time, replay, suspectCn]);

  return (
    <div className="replay">
      <div className="replay-controls">
        <button onClick={() => setPlaying((p) => !p)}>
          {playing ? "⏸ Pause" : "▶ Play"}
        </button>
        <input
          type="range" min={0} max={replay.duration_ms} value={time}
          onChange={(e) => { setPlaying(false); setTime(Number(e.target.value)); }}
        />
        <span className="clock">{(time / 1000).toFixed(1)}s</span>
      </div>
      <canvas ref={canvasRef} width={SIZE} height={SIZE} className="replay-canvas" />
      <div className="legend">
        <span><i className="dot suspect" /> suspect (crosshair path)</span>
        <span><i className="dot ghost" /> honeypot phantom</span>
        <span><i className="dot clean" /> other players</span>
      </div>
    </div>
  );
}

function pointAtGhost(ghost: [number, number, number][], t: number) {
  let found: [number, number, number] | null = null;
  for (const g of ghost) {
    if (g[0] <= t) found = g; else break;
  }
  return found;
}
