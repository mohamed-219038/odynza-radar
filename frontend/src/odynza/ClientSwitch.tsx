/* "Watching for": the client M0 works on, as a card at the top of the M0 agent. Opens an orbit of clients to
   switch between, and "Watch a new company" to add one. */
import { useEffect, useRef, useState } from "react";
import type { ClientInfo } from "../watch/types";

function ClientLogo({ id, name, size = 36 }: { id: number; name: string; size?: number }) {
  const [failed, setFailed] = useState(false);
  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join("") || "?";
  return (
    <span className="odz-clogo" style={{ width: size, height: size, fontSize: Math.round(size * 0.36) }} aria-hidden="true">
      {initials}
      {!failed ? <img src={`/watch/logo/client?client=${id}&v=1`} alt="" loading="lazy" onError={() => setFailed(true)} /> : null}
    </span>
  );
}

export function ClientSwitch({
  info,
  canAdd,
  adding,
  onPick,
  onAdd,
}: {
  info: ClientInfo | null;
  canAdd: boolean;
  adding: boolean;
  onPick: (id: number) => void;
  onAdd: () => void;
}) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !box.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const client = info?.client ?? null;
  const clients = info?.clients ?? [];
  const rivals = info?.counts ? info.counts.confirmed ?? 0 : 0;
  if (!client && !canAdd) return null;
  if (clients.length < 2 && !canAdd)
    return (
      <div className="odz-watching">
        <ClientLogo id={client!.id} name={client!.name} />
        <span>
          <small>Watching for</small>
          <b>{client!.name}</b>
        </span>
      </div>
    );

  return (
    <div className="odz-switch" ref={box}>
      <button className={"odz-watching" + (adding ? " adding" : "")} aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(!open)}>
        {adding || !client ? (
          <span className="odz-clogo new" aria-hidden="true">
            ＋
          </span>
        ) : (
          <ClientLogo id={client.id} name={client.name} />
        )}
        <span>
          <small>{adding || !client ? "Setting up" : "Watching for"}</small>
          <b>{adding || !client ? "A new company" : client.name}</b>
          {!adding && client ? <em>{rivals === 1 ? "1 rival on watch" : `${rivals} rivals on watch`}</em> : null}
        </span>
        <i className="odz-swap" aria-hidden="true">⇅</i>
      </button>
      {open ? (
        <div className="odz-orbit" role="menu" aria-label="Clients">
          <span className="odz-eyebrow">YOUR CLIENTS · {clients.length}</span>
          {clients.map((c) => (
            <button
              key={c.id}
              role="menuitemradio"
              aria-checked={c.id === client?.id && !adding}
              className={"odz-orbit-item" + (c.id === client?.id && !adding ? " current" : "")}
              onClick={() => {
                setOpen(false);
                if (c.id !== client?.id || adding) onPick(c.id);
              }}
            >
              <ClientLogo id={c.id} name={c.name} size={30} />
              <span>
                <b>{c.name}</b>
                <small>{c.website ? c.website.replace(/^https?:\/\/(www\.)?/, "").replace(/\/$/, "") : "No website yet"}</small>
              </span>
              {c.id === client?.id && !adding ? <i className="odz-orbit-dot" aria-hidden="true" /> : null}
            </button>
          ))}
          {canAdd ? (
            <button
              role="menuitem"
              className="odz-orbit-new"
              onClick={() => {
                setOpen(false);
                onAdd();
              }}
            >
              <span className="odz-clogo new" aria-hidden="true">
                ＋
              </span>
              <span>
                <b>Watch a new company</b>
                <small>Its own profile, rivals, briefs and data</small>
              </span>
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
