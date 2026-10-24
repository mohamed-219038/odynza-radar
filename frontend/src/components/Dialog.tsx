import { useEffect, useRef, type ReactNode } from "react";

/** Native <dialog> shown with showModal(): focus trapping, Esc to close and the backdrop come from the browser. */
export function Dialog(props: { id: string; className: string; open: boolean; onClose: () => void; labelledBy?: string; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const { open, onClose } = props;
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    const closed = () => onClose();
    d.addEventListener("close", closed);
    return () => d.removeEventListener("close", closed);
  }, [onClose]);
  return (
    <dialog ref={ref} id={props.id} className={props.className} aria-labelledby={props.labelledBy}>
      {open ? props.children : null}
    </dialog>
  );
}

export function CloseButton({ onClick, label = "Close" }: { onClick: () => void; label?: string }) {
  return (
    <button type="button" className="icon-button" aria-label={label} onClick={onClick}>
      ×
    </button>
  );
}
