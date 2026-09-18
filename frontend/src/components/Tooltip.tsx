import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

/** A single global tooltip layer. Any element carrying a `data-tip` attribute shows a styled
 *  popover INSTANTLY on hover or keyboard focus (no ~1.5 s native `title` delay, and it looks like
 *  the app instead of the OS bubble). Positioned via the trigger's rect and rendered in a portal on
 *  <body>, so it never gets clipped by a card's overflow. Mount once, near the app root. */
export function Tooltip() {
  const [tip, setTip] = useState<{ text: string; rect: DOMRect } | null>(null);

  useEffect(() => {
    const find = (el: EventTarget | null): HTMLElement | null => {
      let n = el as HTMLElement | null;
      while (n && n !== document.body) {
        if (n instanceof HTMLElement && n.dataset.tip) return n;
        n = n.parentElement;
      }
      return null;
    };
    const show = (e: Event) => { const el = find(e.target); if (el) setTip({ text: el.dataset.tip!, rect: el.getBoundingClientRect() }); };
    const hide = (e: Event) => { if (find(e.target)) setTip(null); };
    const clear = () => setTip(null);
    document.addEventListener("mouseover", show);
    document.addEventListener("mouseout", hide);
    document.addEventListener("focusin", show);
    document.addEventListener("focusout", hide);
    window.addEventListener("scroll", clear, true);
    window.addEventListener("resize", clear);
    return () => {
      document.removeEventListener("mouseover", show);
      document.removeEventListener("mouseout", hide);
      document.removeEventListener("focusin", show);
      document.removeEventListener("focusout", hide);
      window.removeEventListener("scroll", clear, true);
      window.removeEventListener("resize", clear);
    };
  }, []);

  if (!tip) return null;
  const { rect, text } = tip;
  const above = rect.top > 140; // flip below when there's no room above
  const left = Math.min(Math.max(10, rect.left), (typeof window !== "undefined" ? window.innerWidth : 1200) - 340);
  const top = above ? rect.top - 8 : rect.bottom + 8;
  return createPortal(
    <div className="tooltip-pop" role="tooltip"
      style={{ position: "fixed", left, top, transform: above ? "translateY(-100%)" : "none" }}>
      {text}
    </div>,
    document.body,
  );
}
