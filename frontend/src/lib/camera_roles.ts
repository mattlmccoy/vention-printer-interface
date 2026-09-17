// Client-side camera role assignment for the setup tiles.
//
// The operator assigns BOTH roles by sight on the live tiles: overview (wide live view) and science
// (bed stills). Each role maps to one browser deviceId; a camera can hold at most one role, and a
// role at most one camera. This is the pure map logic + its localStorage persistence; the browser
// deviceId is the reliable identifier for two identical-model cameras (see webcam.ts).

export type CameraRole = "overview" | "science";
export type RoleChoice = CameraRole | ""; // "" = unassigned

export interface CameraRoleMap {
  overview: string | null; // deviceId
  science: string | null; // deviceId
}

const OVERVIEW_KEY = "vpi.overviewCameraId"; // shared with the dock OverviewCameraPanel
const SCIENCE_KEY = "vpi.scienceCameraId";

/** The role a device currently holds, or "" if none. */
export function roleOf(map: CameraRoleMap, deviceId: string): RoleChoice {
  if (map.overview === deviceId) return "overview";
  if (map.science === deviceId) return "science";
  return "";
}

/** Set (or clear) a device's role, keeping the map consistent: a camera holds at most one role, and
 *  a role at most one camera. Assigning a role evicts the previous holder of THAT role; giving a
 *  device a new role removes it from its OLD role. An empty role clears whatever this device held. */
export function assignRole(map: CameraRoleMap, deviceId: string, role: RoleChoice): CameraRoleMap {
  // Start by removing this device from any role it currently holds.
  const next: CameraRoleMap = {
    overview: map.overview === deviceId ? null : map.overview,
    science: map.science === deviceId ? null : map.science,
  };
  if (role === "overview") next.overview = deviceId; // evicts the old overview holder
  else if (role === "science") next.science = deviceId;
  return next;
}

export function loadRoleMap(storage: Storage | null): CameraRoleMap {
  const get = (k: string): string | null => {
    try { return storage?.getItem(k) || null; } catch { return null; }
  };
  return { overview: get(OVERVIEW_KEY), science: get(SCIENCE_KEY) };
}

/** Persist the map, writing each role's key (or removing it when the role is unassigned) so a
 *  cleared role does not leave a stale saved id behind. */
export function saveRoleMap(storage: Storage | null, map: CameraRoleMap): void {
  const put = (k: string, v: string | null): void => {
    try { if (v) storage?.setItem(k, v); else storage?.removeItem(k); } catch { /* storage disabled */ }
  };
  put(OVERVIEW_KEY, map.overview);
  put(SCIENCE_KEY, map.science);
}
