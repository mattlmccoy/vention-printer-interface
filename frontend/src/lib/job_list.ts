/** Jobs page list shaping. Archived jobs (under the hot folder's _archive/) get their own collapsible
 *  section so the active queue stays short; order within each group is preserved. */
export function splitArchived<T extends { path: string; archived?: boolean }>(
  jobs: readonly T[],
  selectedPath: string | null = null,
): { active: T[]; archived: T[]; selectedIsArchived: boolean } {
  const active = jobs.filter((x) => !x.archived);
  const archived = jobs.filter((x) => !!x.archived);
  // Open the archived section by default when the selected job lives there, so it's never hidden.
  const selectedIsArchived = selectedPath != null && archived.some((x) => x.path === selectedPath);
  return { active, archived, selectedIsArchived };
}
