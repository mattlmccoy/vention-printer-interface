/** A labelled on/off switch whose position IS the state — no contradictory "checkbox + OFF" text.
 *  On = knob right + coloured track; the state word ("on"/"off") matches the knob. */
export function Toggle({ checked, onChange, label, disabled = false, danger = false, title }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
  disabled?: boolean;
  danger?: boolean;
  title?: string;
}) {
  return (
    <span className={`toggle${checked ? " on" : ""}${disabled ? " disabled" : ""}${danger ? " danger" : ""}`} title={title}>
      {label != null && <span className="tg-label">{label}</span>}
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        disabled={disabled}
        className="tg-switch"
        onClick={() => { if (!disabled) onChange(!checked); }}
      >
        <span className="tg-knob" />
      </button>
      <span className="tg-state">{checked ? "on" : "off"}</span>
    </span>
  );
}
