import { useEffect, useState } from "react";
import { api } from "../lib/api.ts";
import { detectOs, inPlaceUpdateCommand, operatorBehind, osFromPlatform } from "../lib/update.ts";

const SITE_VERSION = __APP_VERSION__;  // baked from the backend __version__ at build time
const POLL_MS = 30_000;

/** A top banner shown only when the local operator is OLDER than the version this site was built
 *  from — i.e. the user is on the auto-deployed GitHub Pages site but hasn't updated their local
 *  operator. It shows the one install command (which updates + restarts the operator) for their OS.
 *  Dismissal is remembered per site version, so a newer release re-surfaces it. */
export function UpdateBanner() {
  const [opVersion, setOpVersion] = useState<string | null>(null);
  const [opPlatform, setOpPlatform] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = () => api.health()
      .then((h) => { if (alive) { setOpVersion(h.version ?? null); setOpPlatform(h.platform ?? null); } })
      .catch(() => {});
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  const key = `vpi.updateDismissed.${SITE_VERSION}`;
  useEffect(() => {
    try { setDismissed(localStorage.getItem(key) === "1"); } catch { /* private mode */ }
  }, [key]);

  if (dismissed || !operatorBehind(opVersion, SITE_VERSION)) return null;
  // In-place update for an installed operator, for the OPERATOR's OS. (The install one-liner would
  // regenerate the macOS LaunchAgent plist and drop flags added to it.)
  const { label, command } = inPlaceUpdateCommand(osFromPlatform(opPlatform) ?? detectOs(navigator.userAgent));
  const dismiss = () => { setDismissed(true); try { localStorage.setItem(key, "1"); } catch { /* */ } };
  const copy = () => {
    navigator.clipboard?.writeText(command).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => {});
  };

  return (
    <div className="update-banner" role="status">
      <span className="msg">
        Update available — <b>v{SITE_VERSION}</b>. Your operator is running <b>v{opVersion}</b>.
        Run this on the operator machine ({label}), then reconnect (it restarts itself):
      </span>
      <code className="cmd">{command}</code>
      <button className="small" onClick={copy}>{copied ? "copied" : "copy"}</button>
      <button className="x" aria-label="dismiss" title="dismiss until the next release" onClick={dismiss}>×</button>
    </div>
  );
}
