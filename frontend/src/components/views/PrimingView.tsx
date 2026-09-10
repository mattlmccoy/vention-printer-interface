import { PrimingPanel } from "../PrimingPanel.tsx";
import type { Gates } from "../../lib/format.ts";
import type { StatusPayload } from "../../lib/telemetry.ts";
import { ModuleGrid, type Module } from "../Modules.tsx";
import type { Call } from "./types.ts";

export function PrimingView({ status, gates, call, order, sizes, onOrder, onResize }: { status: StatusPayload | null; gates: Gates; call: Call; order?: string[]; sizes?: Record<string, import("../../lib/console.ts").ModuleSize>; onOrder: (ids: string[]) => void; onResize: (id: string, size: import("../../lib/console.ts").ModuleSize) => void }) {
  const modules: Module[] = [
    { id: "priming", title: "priming (powder prep)", size: "m", node: <PrimingPanel gates={gates} call={call} printState={status?.print.state} /> },
  ];
  return <div className="view modules-view"><ModuleGrid modules={modules} order={order} sizes={sizes} onOrder={onOrder} onResize={onResize} /></div>;
}
