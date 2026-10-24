/* A styled dropdown (React Select) that takes the same <option> children and onChange event shape as a native
   <select>, so forms keep their `set("field")` helpers. The menu opens in place with fixed positioning, which keeps it
   above native <dialog> windows and outside clipped panels. */
import { Children, isValidElement, type ReactNode } from "react";
import ReactSelect, { type SingleValue } from "react-select";
import "./select.css";

type Option = { value: string; label: string; disabled: boolean };

function text(node: ReactNode): string {
  if (node == null || typeof node === "boolean") return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(text).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return text(node.props.children);
  return "";
}

function options(children: ReactNode): Option[] {
  const out: Option[] = [];
  Children.forEach(children, (child) => {
    if (!isValidElement<{ value?: string | number; children?: ReactNode; disabled?: boolean }>(child)) return;
    if (child.type === "option") {
      const label = text(child.props.children);
      out.push({ value: String(child.props.value ?? label), label, disabled: Boolean(child.props.disabled) });
    } else {
      out.push(...options(child.props.children));   // fragments and arrays of options
    }
  });
  return out;
}

export function Select(props: {
  value: string | number;
  onChange: (e: { target: { value: string } }) => void;
  children: ReactNode;
  "aria-label"?: string;
  id?: string;
  name?: string;
  className?: string;
  disabled?: boolean;
  required?: boolean;
}) {
  const list = options(props.children);
  const current = list.find((o) => o.value === String(props.value)) ?? null;
  const small = (props.className ?? "").includes("w-mini-select");
  return (
    <ReactSelect<Option, false>
      inputId={props.id}
      name={props.name}
      aria-label={props["aria-label"]}
      className={"rs" + (small ? " rs-small" : "")}
      classNamePrefix="rs"
      unstyled
      options={list}
      value={current}
      isOptionDisabled={(o) => o.disabled}
      isDisabled={props.disabled}
      isSearchable={list.length > 8}
      required={props.required}
      menuPosition="fixed"
      menuPlacement="auto"
      placeholder={list.length ? "Choose…" : "Nothing to choose yet"}
      noOptionsMessage={() => "No match"}
      onChange={(o: SingleValue<Option>) => o && props.onChange({ target: { value: o.value } })}
    />
  );
}
