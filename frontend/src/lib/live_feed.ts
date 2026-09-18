import { loadRoleMap } from "./camera_roles.ts";

const LIVE_FEED_KEY = "vpi.liveFeedCameraId";

/** The dock is a viewer, not a role editor. Fall back to the assigned overview camera until the
 * operator explicitly chooses a different dock view. */
export function loadLiveFeedCameraId(storage: Storage | null): string | null {
  try {
    return storage?.getItem(LIVE_FEED_KEY) || loadRoleMap(storage).overview;
  } catch {
    return null;
  }
}

export function saveLiveFeedCameraId(storage: Storage | null, deviceId: string): void {
  try {
    storage?.setItem(LIVE_FEED_KEY, deviceId);
  } catch {
    /* private mode / disabled storage: selection lasts for this component session */
  }
}
