export interface Candidate { backend: string; ip: string | null; label: string; reachable: boolean }
export interface ConnectOption { value: string; label: string; ip: string | null }

/** Build connect-menu options: the simulator, each REACHABLE MachineMotion (so an unwired IP is
 *  never offered), then a custom-IP entry. `value` "usb"/"ethernet" carries the candidate label. */
export function connectOptions(cands: Candidate[]): ConnectOption[] {
  const out: ConnectOption[] = [];
  for (const c of cands) {
    if (c.backend === "simulated") out.push({ value: "simulated", label: "simulator", ip: null });
    else if (c.reachable) out.push({ value: c.label, label: `MachineMotion — ${c.label.toUpperCase()} ${c.ip}`, ip: c.ip });
  }
  out.push({ value: "custom", label: "MachineMotion — custom IP", ip: null });
  return out;
}
