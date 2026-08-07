import { useEffect, useMemo, useState } from "react";
import { ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import {
  addGroupMember,
  approveAccessRequest,
  bulkAccessApply,
  bulkAccessPreview,
  createAdminUser,
  createAccessReview,
  createGroup,
  denyAccessRequest,
  getAdminSummary,
  listAccessRequests,
  listAccessReviews,
  listAdminUsers,
  listGroups,
  listOwnershipTransfers,
  platformRoles,
  permissionLevels,
  requestOwnershipTransfer,
  updateAdminUserRole,
  updateAdminUserStatus,
  type AccessRequest,
  type AdminSummary,
  type UserGroup,
} from "../lib/adminSharing";
import type { AtlasUser } from "../lib/datasetLibrary";

export default function AdminConsole() {
  const [summary, setSummary] = useState<AdminSummary | null>(null);
  const [users, setUsers] = useState<AtlasUser[]>([]);
  const [groups, setGroups] = useState<UserGroup[]>([]);
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [message, setMessage] = useState("");
  const [newUser, setNewUser] = useState({ displayName: "", email: "", role: "data_scientist", status: "active" });
  const [newGroup, setNewGroup] = useState({ groupName: "", description: "" });
  const [memberDraft, setMemberDraft] = useState({ groupId: "", userId: "" });
  const [bulkDraft, setBulkDraft] = useState({ groupId: "", resourceType: "project", permissionLevel: "view" });
  const [bulkPreviewCount, setBulkPreviewCount] = useState<number | null>(null);
  const [accessReviews, setAccessReviews] = useState<Array<Record<string, unknown>>>([]);
  const [ownershipTransfers, setOwnershipTransfers] = useState<Array<Record<string, unknown>>>([]);
  const [reviewDraft, setReviewDraft] = useState({ reviewName: "Quarterly access review", resourceType: "project", resourceId: "" });
  const [transferDraft, setTransferDraft] = useState({ resourceType: "project", resourceId: "", toUserId: "" });

  const permissionRows = useMemo(() => summary?.permissionLevels.flatMap((permission) => summary.resourceTypes.slice(0, 8).map((resourceType) => ({ resourceType, permission }))) ?? [], [summary]);

  async function refresh() {
    setMessage("");
    try {
      const [summaryPayload, userPayload, groupPayload, requestPayload, reviewPayload, transferPayload] = await Promise.all([
        getAdminSummary(),
        listAdminUsers(),
        listGroups(),
        listAccessRequests(),
        listAccessReviews().catch(() => ({ reviews: [] })),
        listOwnershipTransfers().catch(() => ({ transfers: [] })),
      ]);
      setSummary(summaryPayload.summary);
      setUsers(userPayload.users);
      setGroups(groupPayload.groups);
      setRequests(requestPayload.requests);
      setAccessReviews(reviewPayload.reviews);
      setOwnershipTransfers(transferPayload.transfers);
      setMemberDraft((current) => ({
        groupId: current.groupId || groupPayload.groups[0]?.group_id || "",
        userId: current.userId || userPayload.users[0]?.userId || "",
      }));
      setBulkDraft((current) => ({ ...current, groupId: current.groupId || groupPayload.groups[0]?.group_id || "" }));
      setTransferDraft((current) => ({ ...current, toUserId: current.toUserId || userPayload.users[0]?.userId || "" }));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS Admin Console is unavailable.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="atlas-page-shell" data-testid="admin-console">
      <section className="rounded-2xl border border-slate-900 bg-slate-950 p-6 text-white shadow-sm">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-sky-200"><ShieldCheck size={16} /> Platform administration</div>
        <h1 className="mt-2 text-2xl font-semibold">ATLAS Admin Console</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-300">Manage users, roles, groups, platform access, and sharing controls for governed analytical work.</p>
        <Link
          to="/admin/bureau-catalogs"
          className="mt-4 inline-flex items-center rounded-lg border border-sky-300/60 bg-sky-400/10 px-3 py-2 text-sm font-semibold text-sky-100 outline-none transition hover:bg-sky-400/20 focus-visible:ring-2 focus-visible:ring-sky-300"
        >
          Open restricted bureau catalog administration
        </Link>
      </section>

      {message && <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{message}</div>}

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-8">
        <Metric label="Total users" value={summary?.totalUsers ?? users.length} />
        <Metric label="Active users" value={summary?.activeUsers ?? users.filter((user) => user.status === "active").length} tone="success" />
        <Metric label="Admins" value={summary?.roleCounts.admin ?? 0} />
        <Metric label="Data scientists" value={summary?.roleCounts.data_scientist ?? 0} />
        <Metric label="Validators" value={summary?.roleCounts.validator ?? 0} />
        <Metric label="Managers" value={summary?.roleCounts.manager ?? 0} />
        <Metric label="Pending requests" value={summary?.pendingAccessRequests ?? requests.filter((request) => request.status === "pending").length} tone="warning" />
        <Metric label="Shared resources" value={summary?.activeSharedResources ?? 0} tone="info" />
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.4fr)_minmax(340px,0.6fr)]">
        <Card title="User Management Table">
          <div className="overflow-auto rounded-xl border border-slate-200">
            <table className="min-w-[980px] w-full text-left text-sm">
              <thead className="bg-slate-100 text-[11px] uppercase tracking-wide text-slate-500">
                <tr><th className="px-3 py-2">Display name</th><th className="px-3 py-2">Email</th><th className="px-3 py-2">Role</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Last active</th><th className="px-3 py-2">Projects owned</th><th className="px-3 py-2">Shared resources</th><th className="px-3 py-2">Evidence captured</th><th className="px-3 py-2">Validations assigned</th><th className="px-3 py-2">Actions</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {users.map((user) => (
                  <tr key={user.userId} className="odd:bg-white even:bg-slate-50/60">
                    <td className="px-3 py-2 font-semibold text-slate-950">{user.displayName}</td>
                    <td className="px-3 py-2">{user.email}</td>
                    <td className="px-3 py-2">
                      <select className="rounded-lg border border-slate-300 px-2 py-1" value={user.role} onChange={async (event) => { await updateAdminUserRole(user.userId, event.target.value); await refresh(); }}>
                        {platformRoles.map((role) => <option key={role} value={role}>{role}</option>)}
                      </select>
                    </td>
                    <td className="px-3 py-2"><StatusBadge status={user.status || "active"} /></td>
                    <td className="px-3 py-2 text-xs">{formatDate(user.lastActiveAt || user.lastLoginAt)}</td>
                    <td className="px-3 py-2 text-center">{user.projectCount ?? 0}</td>
                    <td className="px-3 py-2 text-center">{(user as unknown as { sharedResourceCount?: number }).sharedResourceCount ?? 0}</td>
                    <td className="px-3 py-2 text-center">{user.evidenceCount ?? 0}</td>
                    <td className="px-3 py-2 text-center">{user.validationCount ?? 0}</td>
                    <td className="px-3 py-2">
                      <button className="rounded-lg border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-700" onClick={async () => { await updateAdminUserStatus(user.userId, user.status === "active" ? "inactive" : "active"); await refresh(); }}>
                        {user.status === "active" ? "Deactivate" : "Activate"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Add User Panel">
          <Input label="Display name" value={newUser.displayName} onChange={(value) => setNewUser({ ...newUser, displayName: value })} />
          <Input label="Email" value={newUser.email} onChange={(value) => setNewUser({ ...newUser, email: value })} />
          <label className="atlas-field-label">Role<select className="atlas-input" value={newUser.role} onChange={(event) => setNewUser({ ...newUser, role: event.target.value })}>{platformRoles.map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
          <button className="atlas-primary-button justify-center" onClick={async () => { await createAdminUser(newUser); setNewUser({ displayName: "", email: "", role: "data_scientist", status: "active" }); await refresh(); }}>Create user</button>
        </Card>
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <Card title="Groups and Teams">
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
            <Input label="Group name" value={newGroup.groupName} onChange={(value) => setNewGroup({ ...newGroup, groupName: value })} />
            <Input label="Description" value={newGroup.description} onChange={(value) => setNewGroup({ ...newGroup, description: value })} />
            <button className="atlas-primary-button self-end" onClick={async () => { await createGroup(newGroup); setNewGroup({ groupName: "", description: "" }); await refresh(); }}>Create group</button>
          </div>
          <div className="grid gap-3 md:grid-cols-[1fr_1fr_auto]">
            <label className="atlas-field-label">Group<select className="atlas-input" value={memberDraft.groupId} onChange={(event) => setMemberDraft({ ...memberDraft, groupId: event.target.value })}>{groups.map((group) => <option key={group.group_id} value={group.group_id}>{group.group_name}</option>)}</select></label>
            <label className="atlas-field-label">User<select className="atlas-input" value={memberDraft.userId} onChange={(event) => setMemberDraft({ ...memberDraft, userId: event.target.value })}>{users.map((user) => <option key={user.userId} value={user.userId}>{user.displayName}</option>)}</select></label>
            <button className="atlas-secondary-button self-end" onClick={async () => { await addGroupMember(memberDraft.groupId, memberDraft.userId); await refresh(); }}>Add member</button>
          </div>
          <div className="grid gap-2">{groups.map((group) => <div key={group.group_id} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2"><div className="font-semibold">{group.group_name}</div><div className="text-xs text-slate-500">{group.description || "No description"} / {group.memberCount ?? 0} members / {group.status}</div></div>)}</div>
        </Card>

        <Card title="Access Requests">
          <div className="grid gap-2">
            {requests.length ? requests.map((request) => (
              <div key={request.request_id} className="rounded-xl border border-slate-200 bg-white p-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div><div className="font-semibold">{request.resource_type} / {request.resource_id}</div><div className="text-xs text-slate-500">{request.requester_user_id} requested {request.requested_permission}</div></div>
                  <StatusBadge status={request.status} />
                </div>
                {request.reason && <p className="mt-2 text-sm text-slate-600">{request.reason}</p>}
                {request.status === "pending" && <div className="mt-3 flex gap-2"><button className="atlas-primary-button" onClick={async () => { await approveAccessRequest(request.request_id, "Approved in Admin Console."); await refresh(); }}>Approve</button><button className="atlas-secondary-button" onClick={async () => { await denyAccessRequest(request.request_id, "Denied in Admin Console."); await refresh(); }}>Deny</button></div>}
              </div>
            )) : <div className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-4 text-sm text-slate-500">No access requests are pending.</div>}
          </div>
        </Card>
      </section>

      <section className="grid gap-5 xl:grid-cols-3">
        <Card title="Bulk Access">
          <label className="atlas-field-label">Group<select className="atlas-input" value={bulkDraft.groupId} onChange={(event) => setBulkDraft({ ...bulkDraft, groupId: event.target.value })}>{groups.map((group) => <option key={group.group_id} value={group.group_id}>{group.group_name}</option>)}</select></label>
          <label className="atlas-field-label">Resource type<select className="atlas-input" value={bulkDraft.resourceType} onChange={(event) => setBulkDraft({ ...bulkDraft, resourceType: event.target.value })}><option value="project">Projects</option><option value="dataset">Datasets</option><option value="validation_case">Validation cases</option></select></label>
          <label className="atlas-field-label">Permission<select className="atlas-input" value={bulkDraft.permissionLevel} onChange={(event) => setBulkDraft({ ...bulkDraft, permissionLevel: event.target.value })}>{permissionLevels.map((level) => <option key={level} value={level}>{level}</option>)}</select></label>
          <div className="flex flex-wrap gap-2">
            <button className="atlas-secondary-button" onClick={async () => { const payload = await bulkAccessPreview(bulkDraft); setBulkPreviewCount(payload.preview.affectedCount); }}>Preview affected resources</button>
            <button className="atlas-primary-button" disabled={bulkPreviewCount === null} onClick={async () => { await bulkAccessApply(bulkDraft); setBulkPreviewCount(null); await refresh(); }}>Apply grants</button>
          </div>
          <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">Preview result: {bulkPreviewCount === null ? "Not previewed" : `${bulkPreviewCount} resources affected`}</div>
        </Card>

        <Card title="Access Reviews">
          <Input label="Review name" value={reviewDraft.reviewName} onChange={(value) => setReviewDraft({ ...reviewDraft, reviewName: value })} />
          <label className="atlas-field-label">Resource type<select className="atlas-input" value={reviewDraft.resourceType} onChange={(event) => setReviewDraft({ ...reviewDraft, resourceType: event.target.value })}><option value="project">Project</option><option value="dataset">Dataset</option><option value="validation_case">Validation case</option></select></label>
          <Input label="Resource ID" value={reviewDraft.resourceId} onChange={(value) => setReviewDraft({ ...reviewDraft, resourceId: value })} />
          <button className="atlas-primary-button" onClick={async () => { await createAccessReview(reviewDraft); await refresh(); }}>Create access review</button>
          <div className="grid gap-2">{accessReviews.slice(0, 4).map((review) => <div key={String(review.review_id)} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"><div className="font-semibold">{String(review.review_name)}</div><div className="text-xs text-slate-500">{String(review.status)} / {String((review.items as unknown[] | undefined)?.length ?? 0)} items</div></div>)}</div>
        </Card>

        <Card title="Ownership Transfer">
          <label className="atlas-field-label">Resource type<select className="atlas-input" value={transferDraft.resourceType} onChange={(event) => setTransferDraft({ ...transferDraft, resourceType: event.target.value })}><option value="project">Project</option><option value="dataset">Dataset</option><option value="registry_asset">Registry asset</option></select></label>
          <Input label="Resource ID" value={transferDraft.resourceId} onChange={(value) => setTransferDraft({ ...transferDraft, resourceId: value })} />
          <label className="atlas-field-label">New owner<select className="atlas-input" value={transferDraft.toUserId} onChange={(event) => setTransferDraft({ ...transferDraft, toUserId: event.target.value })}>{users.map((user) => <option key={user.userId} value={user.userId}>{user.displayName}</option>)}</select></label>
          <button className="atlas-secondary-button" onClick={async () => { await requestOwnershipTransfer(transferDraft); await refresh(); }}>Transfer ownership</button>
          <div className="grid gap-2">{ownershipTransfers.slice(0, 4).map((transfer) => <div key={String(transfer.transfer_id)} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"><div className="font-semibold">{String(transfer.resource_type)} / {String(transfer.resource_id)}</div><div className="text-xs text-slate-500">{String(transfer.status)} to {String(transfer.to_user_id)}</div></div>)}</div>
        </Card>
      </section>

      <section className="grid gap-5 xl:grid-cols-2">
        <Card title="Permission Audit">
          <div className="overflow-auto rounded-xl border border-slate-200">
            <table className="min-w-[560px] w-full text-left text-sm">
              <thead className="bg-slate-100 text-[11px] uppercase tracking-wide text-slate-500"><tr><th className="px-3 py-2">Resource</th><th className="px-3 py-2">Permission</th><th className="px-3 py-2">Policy status</th></tr></thead>
              <tbody>{permissionRows.map((row) => <tr key={`${row.resourceType}-${row.permission}`} className="border-t"><td className="px-3 py-2">{row.resourceType}</td><td className="px-3 py-2 font-semibold">{row.permission}</td><td className="px-3 py-2">Supported</td></tr>)}</tbody>
            </table>
          </div>
        </Card>
        <Card title="Platform Access Policies">
          <div className="grid gap-3">
            {Object.entries(summary?.roleDefinitions ?? {}).map(([role, capabilities]) => (
              <div key={role} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                <div className="font-semibold text-slate-950">{role}</div>
                <div className="mt-2 flex flex-wrap gap-1">{capabilities.map((capability) => <span key={capability} className="rounded-full bg-white px-2 py-1 text-xs text-slate-600 ring-1 ring-slate-200">{capability}</span>)}</div>
              </div>
            ))}
          </div>
        </Card>
      </section>
    </div>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="text-base font-semibold text-slate-950">{title}</h2><div className="mt-4 grid gap-3">{children}</div></section>;
}

function Metric({ label, value, tone = "neutral" }: { label: string; value: string | number; tone?: "neutral" | "success" | "warning" | "info" }) {
  const cls = tone === "success" ? "border-emerald-200 bg-emerald-50" : tone === "warning" ? "border-amber-200 bg-amber-50" : tone === "info" ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-white";
  return <div className={`rounded-xl border p-4 shadow-sm ${cls}`}><div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-2 text-xl font-semibold text-slate-950">{value}</div></div>;
}

function Input({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="atlas-field-label">{label}<input className="atlas-input" value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}

function StatusBadge({ status }: { status: string }) {
  const cls = status === "active" || status === "approved" ? "bg-emerald-100 text-emerald-800" : status === "pending" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-700";
  return <span className={`rounded-full px-2 py-1 text-xs font-semibold ${cls}`}>{status}</span>;
}

function formatDate(value?: string) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
