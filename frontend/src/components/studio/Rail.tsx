import type { ReactNode } from "react";

/** Right rail container; sections are passed as children (RailSection). */
export function Rail({ children }: { children: ReactNode }) {
  return <aside className="rail">{children}</aside>;
}
