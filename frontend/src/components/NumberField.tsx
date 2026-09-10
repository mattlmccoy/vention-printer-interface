import { useEffect, useRef, useState, type InputHTMLAttributes } from "react";

/** A number input that is actually editable.
 *
 *  The naive pattern `value={someNumber}` + `onChange={e => set(Number(e.target.value) || old)}`
 *  makes fields impossible to clear: emptying the box snaps it back to a number mid-keystroke, so
 *  you can't delete-then-type. This holds the RAW TEXT you type (empty and intermediate states like
 *  "", "-", "1." are allowed) and only calls `onChange` when the text parses to a finite number.
 *  External `value` changes re-seed the field while you are NOT editing it; on blur an empty/invalid
 *  field snaps back to the current value. */
export function NumberField({
  value,
  onChange,
  ...rest
}: {
  value: number;
  onChange: (n: number) => void;
} & Omit<InputHTMLAttributes<HTMLInputElement>, "value" | "onChange" | "type">) {
  const [text, setText] = useState<string>(String(value));
  const editing = useRef(false);
  useEffect(() => {
    if (!editing.current && Number(text) !== value) setText(String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <input
      {...rest}
      type="number"
      inputMode="decimal"
      value={text}
      onFocus={(e) => { editing.current = true; rest.onFocus?.(e); }}
      onBlur={(e) => { editing.current = false; setText(String(value)); rest.onBlur?.(e); }}
      onChange={(e) => {
        const s = e.target.value;
        setText(s);
        const nx = Number(s);
        if (s.trim() !== "" && Number.isFinite(nx)) onChange(nx);
      }}
    />
  );
}
