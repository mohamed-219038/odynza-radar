/* Team (admins only): approve sign-ups, add accounts, switch roles, reset passwords, disable or delete accounts. */
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { json, request } from "../api";
import { Select } from "../components/Select";
import { useToast } from "../components/Toast";
import { date } from "../format";
import type { ManagedUser, User } from "../types";

const ROLE_NAMES: Record<ManagedUser["role"], string> = {
  admin: "Admin",
  member: "Team member",
  viewer: "Viewer (read-only)",
  client: "Client (Competitor watch only)",
  pending: "Waiting for approval",
};
const ROLE_OPTIONS: User["role"][] = ["member", "viewer", "client", "admin"];

export function TeamPage({ me, onChange }: { me: User; onChange?: (pending: number) => void }) {
  const toast = useToast();
  const [users, setUsers] = useState<ManagedUser[] | null>(null);
  const [error, setError] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<User["role"]>("member");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const list = await request<ManagedUser[]>("/auth/users");
      setUsers(list);
      setError("");
      onChange?.(list.filter((u) => u.role === "pending").length);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [onChange]);

  useEffect(() => {
    load();
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const u = await request<ManagedUser>("/auth/users", json({ username: username.trim(), password, role }));
      toast(`Account ${u.username} created. Share the password with them privately.`);
      setUsername("");
      setPassword("");
      setRole("member");
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function update(u: ManagedUser, change: Partial<{ role: string; disabled: boolean; password: string }>, done: string) {
    try {
      await request(`/auth/users/${u.id}`, { method: "PATCH", body: JSON.stringify(change) });
      toast(done);
      await load();
    } catch (err) {
      toast((err as Error).message);
    }
  }

  async function reset(u: ManagedUser) {
    const pw = window.prompt(`New password for ${u.username} (at least 10 characters). They are signed out everywhere.`);
    if (pw) await update(u, { password: pw }, `Password reset for ${u.username}.`);
  }

  async function remove(u: ManagedUser) {
    const ask =
      u.role === "pending"
        ? `Reject the sign-up from ${u.username}? Their account is deleted.`
        : `Delete the account ${u.username}? Their plans and batches stay. This cannot be undone.`;
    if (!window.confirm(ask)) return;
    try {
      await request(`/auth/users/${u.id}`, { method: "DELETE" });
      toast(u.role === "pending" ? `Sign-up from ${u.username} rejected.` : `Account ${u.username} deleted.`);
      await load();
    } catch (err) {
      toast((err as Error).message);
    }
  }

  const sorted = users ? [...users].sort((a, b) => Number(b.role === "pending") - Number(a.role === "pending")) : null;
  const pending = users?.filter((u) => u.role === "pending").length ?? 0;

  return (
    <div className="odz-team">
      <p className="muted">
        Team members can do everything except manage accounts. Viewers can only look and download. Clients see only Competitor watch
        for their own company (link them under Profile › Client logins). Admins also manage this page.
      </p>
      {error ? <div className="alert">{error}</div> : null}
      <section className="w-panel">
        <h3 className="w-sub">
          Accounts {pending ? <span className="badge running">{pending} waiting for approval</span> : null}
        </h3>
        {!sorted ? (
          <p className="muted">Loading accounts…</p>
        ) : (
          <ul className="odz-team-list">
            {sorted.map((u) => (
              <li key={u.id} className={"odz-team-row" + (u.role === "pending" ? " pending" : "")}>
                <span className="odz-avatar" aria-hidden="true">
                  {u.username.slice(0, 1).toUpperCase()}
                </span>
                <div className="odz-team-name">
                  <b>{u.username}</b> {u.id === me.id ? <span className="badge neutral">you</span> : null}{" "}
                  {u.disabled ? <span className="badge warn">disabled</span> : null}
                  <small>
                    {u.role === "pending"
                      ? `Signed up ${date(u.created_at)} · cannot sign in until approved`
                      : `${ROLE_NAMES[u.role]} · last sign-in ${u.last_login_at ? date(u.last_login_at) : "never"}`}
                  </small>
                </div>
                <div className="odz-team-actions">
                  {u.role === "pending" ? (
                    <>
                      <button type="button" className="button primary small-button" onClick={() => update(u, { role: "member" }, `${u.username} approved as a team member.`)}>
                        Approve as member
                      </button>
                      <button type="button" className="button secondary small-button" onClick={() => update(u, { role: "viewer" }, `${u.username} approved as a viewer.`)}>
                        Approve as viewer
                      </button>
                      <button type="button" className="button secondary small-button" onClick={() => remove(u)}>
                        Reject
                      </button>
                    </>
                  ) : u.id !== me.id ? (
                    <>
                      <Select
                        aria-label={`Role for ${u.username}`}
                        value={u.role}
                        onChange={(e) => update(u, { role: e.target.value }, `${u.username} is now: ${ROLE_NAMES[e.target.value as User["role"]]}.`)}
                      >
                        {ROLE_OPTIONS.map((r) => (
                          <option key={r} value={r}>
                            {ROLE_NAMES[r]}
                          </option>
                        ))}
                      </Select>
                      <button
                        type="button"
                        className="button secondary small-button"
                        onClick={() => update(u, { disabled: !u.disabled }, `${u.username} ${u.disabled ? "can sign in again" : "is disabled and signed out"}.`)}
                      >
                        {u.disabled ? "Enable" : "Disable"}
                      </button>
                      <button type="button" className="button secondary small-button" onClick={() => reset(u)}>
                        Reset password
                      </button>
                      <button type="button" className="button secondary small-button" onClick={() => remove(u)}>
                        Delete
                      </button>
                    </>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
      <form className="w-panel w-form odz-team-add" onSubmit={add}>
        <h3 className="w-sub">Add an account</h3>
        <div className="odz-team-fields">
          <label>
            Username
            <input required minLength={3} maxLength={64} autoComplete="off" value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label>
            Role
            <Select aria-label="Role" value={role} onChange={(e) => setRole(e.target.value as User["role"])}>
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {ROLE_NAMES[r]}
                </option>
              ))}
            </Select>
          </label>
          <label>
            Temporary password <span className="optional">at least 10 characters</span>
            <input type="password" autoComplete="new-password" required minLength={10} maxLength={256} value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
        </div>
        <div className="dialog-actions">
          <button type="submit" className="button primary" disabled={busy}>
            {busy ? "Adding…" : "Add account"}
          </button>
        </div>
      </form>
    </div>
  );
}
