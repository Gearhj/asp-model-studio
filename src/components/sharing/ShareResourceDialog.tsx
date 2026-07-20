import { useEffect, useMemo, useState } from "react";
import { Share2, X } from "lucide-react";
import {
  getSharingStatus,
  listAdminUsers,
  listGroups,
  permissionLevels,
  revokeShare,
  shareResource,
  type ResourcePermission,
  type SharingStatus,
  type UserGroup,
} from "../../lib/adminSharing";
import type { AtlasUser } from "../../lib/datasetLibrary";

export type ShareResourceDialogProps = {
  open: boolean;
  onClose: () => void;
  resourceType: string;
  resourceId: string;
  resourceName: string;
};

export default function ShareResourceDialog({ open, onClose, resourceType, resourceId, resourceName }: ShareResourceDialogProps) {
  const [users, setUsers] = useState<AtlasUser[]>([]);
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [status, setStatus] = useState<SharingStatus | null>(null);
  const [targetKind, setTargetKind] = useState<"user" | "group">("user");
  const [principalId, setPrincipalId] = useState("");
  const [permissionLevel, setPermissionLevel] = useState("view");
  const [message, setMessage] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [expirationMode, setExpirationMode] = useState("none");
  const [targetSearch, setTargetSearch] = useState("");
  const [notify, setNotify] = useState(false);
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState("");

  const selectableTargets = useMemo(() => {
    const allTargets = targetKind === "user"
      ? users.map((user) => ({ id: user.userId, label: `${user.displayName} (${user.role} / ${user.status})` }))
      : groups.map((group) => ({ id: group.group_id, label: `${group.group_name} (${group.memberCount ?? 0} members)` }));
    const query = targetSearch.trim().toLowerCase();
    return query ? allTargets.filter((target) => target.label.toLowerCase().includes(query) || target.id.toLowerCase().includes(query)) : allTargets;
  }, [groups, targetKind, targetSearch, users]);

  async function refresh() {
    if (!open) return;
    const [userPayload, groupPayload, sharingPayload] = await Promise.all([
      listAdminUsers().catch(() => ({ users: [] })),
      listGroups().catch(() => ({ groups: [] })),
      getSharingStatus(resourceType, resourceId).catch(() => null),
    ]);
    setUsers(userPayload.users);
    setGroups(groupPayload.groups);
    setStatus(sharingPayload?.sharing ?? null);
    const targets = targetKind === "user" ? userPayload.users : groupPayload.groups;
    if (!principalId && targets[0]) setPrincipalId(targetKind === "user" ? (targets[0] as AtlasUser).userId : (targets[0] as UserGroup).group_id);
  }

  useEffect(() => {
    void refresh();
  }, [open, resourceType, resourceId]);

  useEffect(() => {
    const first = selectableTargets[0];
    setPrincipalId(first?.id ?? "");
  }, [targetKind]);

  if (!open) return null;

  async function submit() {
    if (!principalId) {
      setFeedback("Select a user or group before sharing.");
      return;
    }
    setBusy(true);
    setFeedback("");
    try {
      const computedExpiresAt = expirationMode === "7" ? daysFromNow(7) : expirationMode === "30" ? daysFromNow(30) : expirationMode === "custom" ? expiresAt : undefined;
      await shareResource({
        resourceType,
        resourceId,
        principalType: targetKind,
        principalId,
        permissionLevel,
        message,
        expiresAt: computedExpiresAt,
      });
      setFeedback("Access was granted and recorded in the audit log.");
      await refresh();
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "ATLAS could not share this resource.");
    } finally {
      setBusy(false);
    }
  }

  async function revoke(permission: ResourcePermission) {
    setBusy(true);
    setFeedback("");
    try {
      await revokeShare(resourceType, resourceId, permission.principal_type, permission.principal_id);
      setFeedback("Access was revoked and recorded in the audit log.");
      await refresh();
    } catch (error) {
      setFeedback(error instanceof Error ? error.message : "ATLAS could not revoke this share.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 px-4 py-6">
      <section className="max-h-[92vh] w-full max-w-4xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-slate-200 bg-slate-950 px-5 py-4 text-white">
          <div>
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-sky-200"><Share2 size={15} /> Governed sharing</div>
            <h2 className="mt-1 text-xl font-semibold">Share {resourceName}</h2>
            <p className="mt-1 text-sm text-slate-300">{resourceType} / {resourceId}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg border border-white/20 p-2 text-white hover:bg-white/10" aria-label="Close share dialog">
            <X size={18} />
          </button>
        </header>
        <div className="grid max-h-[calc(92vh-84px)] gap-5 overflow-y-auto p-5 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
          <div className="space-y-4">
            <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
              <div className="text-sm font-semibold text-blue-950">Grant access</div>
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                Sharing regulated datasets, evidence, documentation, or scored outputs may expose sensitive information. Confirm the recipient has a business need.
              </div>
              <div className="mt-3 grid gap-3">
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Share with
                  <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm normal-case text-slate-950" value={targetKind} onChange={(event) => setTargetKind(event.target.value as "user" | "group")}>
                    <option value="user">User</option>
                    <option value="group">Group</option>
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Search {targetKind}
                  <input className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm normal-case text-slate-950" value={targetSearch} onChange={(event) => setTargetSearch(event.target.value)} placeholder={targetKind === "user" ? "Search by name, role, or ID" : "Search group or team"} />
                </label>
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Recipient
                  <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm normal-case text-slate-950" value={principalId} onChange={(event) => setPrincipalId(event.target.value)}>
                    {selectableTargets.map((target) => <option key={target.id} value={target.id}>{target.label}</option>)}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Permission level
                  <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm normal-case text-slate-950" value={permissionLevel} onChange={(event) => setPermissionLevel(event.target.value)}>
                    {permissionLevels.map((level) => <option key={level} value={level}>{level}</option>)}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Optional expiration
                  <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm normal-case text-slate-950" value={expirationMode} onChange={(event) => setExpirationMode(event.target.value)}>
                    <option value="none">None</option>
                    <option value="7">7 days</option>
                    <option value="30">30 days</option>
                    <option value="custom">Custom date</option>
                  </select>
                </label>
                {expirationMode === "custom" && <input className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm normal-case text-slate-950" type="date" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} />}
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Optional message
                  <textarea className="min-h-20 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm normal-case text-slate-950" value={message} onChange={(event) => setMessage(event.target.value)} />
                </label>
                <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700">
                  <input type="checkbox" checked={notify} onChange={(event) => setNotify(event.target.checked)} />
                  Notify recipient
                </label>
                {notify && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">
                    Notification delivery is local to ATLAS. Email delivery is not enabled.
                  </div>
                )}
                <button type="button" disabled={busy || !principalId} onClick={submit} className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">
                  Share Resource
                </button>
              </div>
            </div>
            {feedback && <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{feedback}</div>}
          </div>
          <div className="space-y-4">
            <AccessSummary status={status} />
            <section className="rounded-xl border border-slate-200 bg-white">
              <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-950">Current access</div>
              <div className="max-h-80 overflow-auto">
                {status?.permissions?.length ? (
                  <table className="w-full text-left text-sm">
                    <thead className="bg-slate-50 text-[11px] uppercase tracking-wide text-slate-500">
                      <tr><th className="px-3 py-2">Principal</th><th className="px-3 py-2">Permission</th><th className="px-3 py-2">Granted by</th><th className="px-3 py-2">Granted</th><th className="px-3 py-2">Expires</th><th className="px-3 py-2">Action</th></tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                      {status.permissions.map((permission) => (
                        <tr key={permission.permission_id}>
                          <td className="px-3 py-2">{permission.principal_type}: {permission.principal_id}</td>
                          <td className="px-3 py-2 font-semibold">{permission.permission_level}</td>
                          <td className="px-3 py-2 text-xs text-slate-500">{permission.granted_by_user_id || "Unknown"}</td>
                          <td className="px-3 py-2 text-xs text-slate-500">{formatDate(permission.granted_at)}</td>
                          <td className="px-3 py-2 text-xs text-slate-500">{formatDate(permission.expires_at)}</td>
                          <td className="px-3 py-2"><button type="button" onClick={() => revoke(permission)} className="rounded border border-red-200 px-2 py-1 text-xs font-semibold text-red-700">Revoke</button></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : <div className="p-4 text-sm text-slate-500">No explicit shares recorded yet.</div>}
              </div>
            </section>
            <section className="rounded-xl border border-slate-200 bg-white">
              <div className="border-b border-slate-100 px-4 py-3 text-sm font-semibold text-slate-950">Sharing history</div>
              <div className="max-h-56 overflow-auto p-3">
                {status?.events?.length ? status.events.map((event) => (
                  <div key={event.sharing_event_id} className="border-b border-slate-100 py-2 text-sm last:border-0">
                    <div className="font-semibold text-slate-800">{event.principal_type} {event.principal_id} / {event.permission_level}</div>
                    <div className="text-xs text-slate-500">Shared by {event.shared_by_user_id} on {formatDate(event.created_at)}</div>
                  </div>
                )) : <div className="text-sm text-slate-500">No sharing events recorded yet.</div>}
              </div>
            </section>
          </div>
        </div>
      </section>
    </div>
  );
}

function AccessSummary({ status }: { status: SharingStatus | null }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-sm font-semibold text-slate-950">Access summary</div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <Fact label="Owner" value={status?.ownerUserId || "Not recorded"} />
        <Fact label="Your permission" value={status?.currentUserPermission?.permission || "Not loaded"} />
        <Fact label="Users/groups" value={String(status?.permissions?.length ?? 0)} />
        <Fact label="Access history" value={`${status?.events?.length ?? 0} events`} />
      </div>
    </section>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-200 bg-white px-3 py-2"><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 break-all text-sm font-semibold text-slate-950">{value}</div></div>;
}

function formatDate(value?: string) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function daysFromNow(days: number) {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return date.toISOString().slice(0, 10);
}
