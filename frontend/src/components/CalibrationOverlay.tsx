import type { Pt } from "../lib/overlay_geom.ts";

/** Overlay drawn on the active calibration image, in that image's pixel coordinates:
 *  the area covered so far (green), each ArUco marker outline (amber), marker corners (amber dots)
 *  and chessboard corners (green dots, with their ChArUco id when given). */
export function CalibrationOverlay({ size, chess, markers, quads, hull, chessIds }: {
  size: [number, number];
  chess: Pt[];
  markers: Pt[];
  quads?: Pt[][];
  hull?: Pt[];
  chessIds?: number[];
}) {
  const [w, h] = size;
  const r = Math.max(3, w / 220);
  const stroke = Math.max(1, w / 500);
  const font = Math.max(10, w / 70);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true"
         style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }}>
      {hull && hull.length >= 3 && (
        <polygon points={hull.map((p) => p.join(",")).join(" ")} fill="#3fd17a" fillOpacity={0.12} stroke="#3fd17a" strokeWidth={stroke * 2} strokeDasharray={`${stroke * 6} ${stroke * 4}`} />
      )}
      {(quads ?? []).map((q, i) => (
        <polygon key={`q${i}`} points={q.map((p) => p.join(",")).join(" ")} fill="none" stroke="#ffb347" strokeWidth={stroke} />
      ))}
      {markers.map(([x, y], i) => <circle key={`m${i}`} cx={x} cy={y} r={r * 0.7} fill="#ffb347" />)}
      {chess.map(([x, y], i) => (
        <g key={`c${i}`}>
          <circle cx={x} cy={y} r={r} fill="#3fd17a" stroke="#0b0f14" strokeWidth={stroke / 2} />
          {chessIds && <text x={x + r * 1.4} y={y - r * 1.4} fontSize={font} fill="#3fd17a" stroke="#0b0f14" strokeWidth={stroke / 2} paintOrder="stroke">{chessIds[i]}</text>}
        </g>
      ))}
    </svg>
  );
}
