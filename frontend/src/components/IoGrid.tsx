import { tri } from "../lib/format.ts";
import type { StatusPayload } from "../lib/telemetry.ts";

export function IoGrid({ status, pollHz }: { status: StatusPayload | null; pollHz: number | null }) {
  const t = status?.controller.telemetry;
  const cls = (v: boolean | null | undefined, badWhen: boolean | null) => (v === null || v === undefined ? "unk" : v === badWhen ? "bad" : "");
  return (
    <div className="io">
      <div className={cls(t?.estop_triggered, true)}><span>e-stop</span><b>{tri(t?.estop_triggered, "ASSERTED", "clear")}</b></div>
      <div className={cls(t?.drives_ready, false)}><span>drives</span><b>{tri(t?.drives_ready, "ready", "NOT READY")}</b></div>
      <div className={t && !t.health_ok ? "bad" : ""}><span>health</span><b>{t ? (t.health_ok ? "ok" : "BAD") : "?"}</b></div>
      <div><span>poll</span><b>{pollHz === null ? "—" : `${pollHz.toFixed(1)} Hz`}</b></div>
      <div className={status?.controller.read_error ? "bad" : ""}><span>read</span><b>{status?.controller.read_error ? "ERROR" : "ok"}</b></div>
      <div><span>backend</span><b>{status?.controller.backend ?? "none"}</b></div>
    </div>
  );
}
