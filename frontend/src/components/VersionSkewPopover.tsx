import { useState } from "react";
import { detectOs, inPlaceUpdateCommand, mismatchAdvice, osFromPlatform } from "../lib/update.ts";

/** Opened from the status-bar version badge when console ≠ operator: says which side is behind and,
 *  when the operator needs updating, the in-place update command for the OPERATOR's OS (from its own
 *  /api/health platform, falling back to this browser's), with copy. */
export function VersionSkewPopover({ siteVersion, siteBuild, opVersion, opBuild, platform, onChangelog, onClose }: {
  siteVersion: string; siteBuild: string; opVersion: string | null; opBuild: string | null; platform: string | null;
  onChangelog: () => void; onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const advice = mismatchAdvice({ siteVersion, opVersion });
  const os = osFromPlatform(platform) ?? detectOs(typeof navigator === "undefined" ? "" : navigator.userAgent);
  const { label, command } = inPlaceUpdateCommand(os);
  const copy = () => {
    navigator.clipboard?.writeText(command).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); }).catch(() => {});
  };
  return (
    <div className="skew-pop" role="dialog" aria-label="console and operator differ">
      <div className="skew-head">
        <b>Console ≠ operator</b>
        <button className="x" aria-label="close" onClick={onClose}>×</button>
      </div>
      <div className="skew-row"><span>console</span><code>v{siteVersion}{siteBuild ? `·${siteBuild}` : ""}</code></div>
      <div className="skew-row"><span>operator</span><code>v{opVersion ?? "?"}{opBuild ? `·${opBuild}` : ""}</code></div>
      <p>{advice.text}</p>
      {advice.showCommand && (
        <>
          <div className="skew-label">{label} · on the operator machine</div>
          <div className="skew-cmd"><code>{command}</code><button className="small" onClick={copy}>{copied ? "copied" : "copy"}</button></div>
          <p className="hint" style={{ marginTop: 0 }}>Uses the default checkout <code>~/vention-printer-interface</code>. It stops if that checkout has uncommitted changes.</p>
        </>
      )}
      <button className="linklike" onClick={onChangelog}>what changed? (changelog)</button>
    </div>
  );
}
