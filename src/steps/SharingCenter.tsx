import { useEffect, useState } from "react";
import { Inbox, Send, ShieldQuestion } from "lucide-react";
import {
  listAccessRequests,
  sharedByMe,
  sharedWithMe,
  type AccessRequest,
  type ResourcePermission,
  type SharingEvent,
} from "../lib/adminSharing";

export default function SharingCenter() {
  const [activeTab, setActiveTab] = useState<"with-me" | "by-me" | "requests">("with-me");
  const [withMe, setWithMe] = useState<ResourcePermission[]>([]);
  const [byMe, setByMe] = useState<SharingEvent[]>([]);
  const [requests, setRequests] = useState<AccessRequest[]>([]);
  const [message, setMessage] = useState("");

  async function refresh() {
    setMessage("");
    try {
      const [withPayload, byPayload, requestPayload] = await Promise.all([
        sharedWithMe(),
        sharedByMe(),
        listAccessRequests().catch(() => ({ requests: [] })),
      ]);
      setWithMe(withPayload.resources);
      setByMe(byPayload.resources);
      setRequests(requestPayload.requests);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS sharing records are unavailable.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="atlas-page-shell" data-testid="sharing-center">
      <section className="rounded-2xl border border-slate-900 bg-slate-950 p-6 text-white shadow-sm">
        <div className="text-xs font-semibold uppercase tracking-[0.16em] text-sky-200">Collaboration</div>
        <h1 className="mt-2 text-2xl font-semibold">Sharing Center</h1>
        <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-300">Review resources shared with you, resources you shared, and access requests across governed ATLAS work.</p>
      </section>

      {message && <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{message}</div>}

      <div className="flex flex-wrap gap-2 rounded-xl border border-slate-200 bg-white p-2 shadow-sm">
        <Tab active={activeTab === "with-me"} icon={<Inbox size={15} />} label="Shared with Me" onClick={() => setActiveTab("with-me")} />
        <Tab active={activeTab === "by-me"} icon={<Send size={15} />} label="Shared by Me" onClick={() => setActiveTab("by-me")} />
        <Tab active={activeTab === "requests"} icon={<ShieldQuestion size={15} />} label="Access Requests" onClick={() => setActiveTab("requests")} />
      </div>

      {activeTab === "with-me" && (
        <ShareTable
          title="Shared with Me"
          headers={["Resource name", "Resource type", "Shared by", "Permission", "Shared date", "Last updated", "Action"]}
          rows={withMe.map((row) => [row.resource_id, row.resource_type, row.granted_by_user_id || "Unknown", row.permission_level, formatDate(row.granted_at), formatDate(row.granted_at), "Open"])}
          empty="No resources have been shared with you yet."
        />
      )}
      {activeTab === "by-me" && (
        <ShareTable
          title="Shared by Me"
          headers={["Resource name", "Resource type", "Shared with", "Permission", "Shared date", "Expires", "Revoke"]}
          rows={byMe.map((row) => [row.resource_id, row.resource_type, `${row.principal_type}: ${row.principal_id}`, row.permission_level, formatDate(row.created_at), "Not set", "Manage"])}
          empty="You have not shared any resources yet."
        />
      )}
      {activeTab === "requests" && (
        <ShareTable
          title="Access Requests"
          headers={["Resource", "Requester", "Requested permission", "Reason", "Status", "Requested date", "Action"]}
          rows={requests.map((row) => [`${row.resource_type}: ${row.resource_id}`, row.requester_user_id, row.requested_permission, row.reason || "", row.status, formatDate(row.created_at), row.status === "pending" ? "Review in Admin Console" : "Recorded"])}
          empty="No access requests are recorded."
        />
      )}
    </div>
  );
}

function Tab({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return <button type="button" onClick={onClick} className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold ${active ? "bg-slate-950 text-white" : "text-slate-600 hover:bg-slate-50"}`}>{icon}{label}</button>;
}

function ShareTable({ title, headers, rows, empty }: { title: string; headers: string[]; rows: string[][]; empty: string }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">{title}</h2>
      <div className="mt-4 overflow-auto rounded-xl border border-slate-200">
        {rows.length ? (
          <table className="min-w-[860px] w-full text-left text-sm">
            <thead className="bg-slate-100 text-[11px] uppercase tracking-wide text-slate-500"><tr>{headers.map((header) => <th key={header} className="px-3 py-2">{header}</th>)}</tr></thead>
            <tbody className="divide-y divide-slate-100">{rows.map((row, index) => <tr key={index} className="odd:bg-white even:bg-slate-50/60">{row.map((value, cell) => <td key={`${index}-${cell}`} className="px-3 py-2">{value}</td>)}</tr>)}</tbody>
          </table>
        ) : <div className="p-6 text-sm text-slate-500">{empty}</div>}
      </div>
    </section>
  );
}

function formatDate(value?: string) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
