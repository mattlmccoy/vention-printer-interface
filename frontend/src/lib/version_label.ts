/** Status-bar version label. Always shows the operator's version AND commit next to the console's,
 *  so an operator update is visible even when the hand-bumped semver is unchanged. `buildsDiffer`
 *  flags a console/operator commit mismatch — the version-skew case where the console (GitHub
 *  Pages) runs ahead of the local operator and newer features can silently degrade. */
export function versionLabel(p: {
  siteVersion: string;
  siteBuild: string;
  opVersion: string | null;
  opBuild: string | null;
}): { text: string; buildsDiffer: boolean } {
  const tag = (v: string, b: string | null) => `v${v}${b ? `·${b}` : ""}`;
  const console_ = `console ${tag(p.siteVersion, p.siteBuild || null)}`;
  if (!p.opVersion) return { text: console_, buildsDiffer: false };
  const buildsDiffer = !!p.siteBuild && !!p.opBuild && p.siteBuild !== p.opBuild;
  return { text: `${console_} · op ${tag(p.opVersion, p.opBuild)}`, buildsDiffer };
}
