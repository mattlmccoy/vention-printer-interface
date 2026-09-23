/** Floating alert helpers. Controller warnings now float over the page (no layout shift), so the
 *  operator can dismiss them; a dismissed set stays hidden until the warnings actually change. */

/** Order-insensitive identity of a warning set (so a reordering alone doesn't re-show it). */
export function warningsKey(warnings: readonly string[]): string {
  return [...warnings].sort().join("␞");
}

/** Show the warnings banner when there are warnings and they differ from the dismissed set. */
export function showWarnings(warnings: readonly string[] | undefined, dismissedKey: string | null): boolean {
  if (!warnings || warnings.length === 0) return false;
  return warningsKey(warnings) !== dismissedKey;
}
