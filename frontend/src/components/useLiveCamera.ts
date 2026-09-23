import { useCallback, useEffect, useRef, useState } from "react";
import { cameraBus } from "../lib/camera_bus.ts";

const BACKOFF_MS = [1000, 2000, 5000, 10000];

/** Hooks a live camera view into the shared camera bus (camera_bus.ts) and keeps it alive:
 *  - bus PAUSE (a full-res science still is being taken with that camera alone): stop the stream and
 *    report `paused`; bus RESUME: reopen.
 *  - the track ENDS on its own (camera dropped off USB, e.g. a cable pulled at a gantry end): report
 *    `dropped` and reopen with backoff, instead of sitting black until a page reload.
 *  `watch(track)` must be called with each newly opened track. */
export function useLiveCamera(stop: () => void, reopen: () => void): {
  paused: boolean;
  dropped: boolean;
  watch: (track: MediaStreamTrack | null) => void;
} {
  const [paused, setPaused] = useState(() => cameraBus.paused());
  const [dropped, setDropped] = useState(false);
  const stopRef = useRef(stop);
  const reopenRef = useRef(reopen);
  stopRef.current = stop;
  reopenRef.current = reopen;
  const attempt = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const off = cameraBus.subscribe({
      pause: () => { setPaused(true); stopRef.current(); },
      resume: () => { setPaused(false); reopenRef.current(); },
    });
    return () => { off(); if (timer.current) clearTimeout(timer.current); };
  }, []);

  const watch = useCallback((track: MediaStreamTrack | null) => {
    if (!track) return;
    attempt.current = 0;
    setDropped(false);
    track.addEventListener("ended", () => {
      if (cameraBus.paused()) return; // we stopped it on purpose for a still
      setDropped(true);
      const wait = BACKOFF_MS[Math.min(attempt.current, BACKOFF_MS.length - 1)];
      attempt.current += 1;
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => reopenRef.current(), wait);
    }, { once: true });
  }, []);

  return { paused, dropped, watch };
}
