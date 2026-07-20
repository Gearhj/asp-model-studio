import { useState } from "react";
import { requestAccess, permissionLevels } from "../../lib/adminSharing";

export default function AccessDeniedRequest({ resourceType, resourceId, resourceName }: { resourceType: string; resourceId: string; resourceName?: string }) {
  const [requestedPermission, setRequestedPermission] = useState("view");
  const [reason, setReason] = useState("");
  const [message, setMessage] = useState("");

  return (
    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-950">
      <h2 className="text-lg font-semibold">Access required</h2>
      <p className="mt-2 text-sm leading-6">You do not currently have access to {resourceName || `${resourceType} ${resourceId}`}. Request access from the owner or an administrator.</p>
      <div className="mt-4 grid gap-3 md:grid-cols-[220px_minmax(0,1fr)_auto]">
        <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide">
          Requested permission
          <select className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm normal-case text-slate-950" value={requestedPermission} onChange={(event) => setRequestedPermission(event.target.value)}>
            {permissionLevels.map((level) => <option key={level} value={level}>{level}</option>)}
          </select>
        </label>
        <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide">
          Reason
          <input className="rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm normal-case text-slate-950" value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Describe the business need." />
        </label>
        <button className="self-end rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={async () => { await requestAccess(resourceType, resourceId, requestedPermission, reason); setMessage("Access request submitted."); }}>Request Access</button>
      </div>
      {message && <div className="mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">{message}</div>}
    </section>
  );
}
