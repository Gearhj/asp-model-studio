import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { FileClock, LockKeyhole, LogOut, ShieldCheck, UserPlus, Users } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import {
  adminCreateUser,
  adminDisableUser,
  adminEnableUser,
  adminSetRole,
  adminUnlockUser,
  adminUsers,
  auditEvents,
  changePassword,
  login,
  logout,
  me,
  register,
} from "../lib/auth";
import { listDatasets, listProjectDatasets, type AtlasUser, type DatasetSummary, type ProjectDatasetLink } from "../lib/datasetLibrary";
import { loadLocalProjects } from "../lib/localProjects";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { safeAuthReturnPath } from "../lib/authReturnPath";
import { auditExportUrl, searchAuditLog, type AuditEvent } from "../lib/adminSharing";

const roles = ["admin", "data_scientist", "validator", "manager", "viewer", "data_steward", "model_owner", "model_manager", "auditor"];
const KEEP_SIGNED_IN_EMAIL_KEY = "asp-model-studio-keep-signed-in-email";

type AuthPageProps = {
  onAuthenticated?: (user: AtlasUser) => void;
};

export function LoginPage({ onAuthenticated }: AuthPageProps = {}) {
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState(() => localStorage.getItem(KEEP_SIGNED_IN_EMAIL_KEY) || "admin@aspmodelstudio.local");
  const [password, setPassword] = useState("");
  const [keepSignedIn, setKeepSignedIn] = useState(() => Boolean(localStorage.getItem(KEEP_SIGNED_IN_EMAIL_KEY)));
  const [message, setMessage] = useState("");

  async function submit() {
    setMessage("");
    try {
      const response = await login(email, password);
      if (keepSignedIn) {
        localStorage.setItem(KEEP_SIGNED_IN_EMAIL_KEY, email);
      } else {
        localStorage.removeItem(KEEP_SIGNED_IN_EMAIL_KEY);
      }
      onAuthenticated?.(response.user);
      const returnTo = safeAuthReturnPath(new URLSearchParams(location.search).get("returnTo"));
      navigate(returnTo || "/dashboard", { replace: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Sign in failed. Check your email and password.");
    }
  }

  return (
    <AuthShell title="Sign in to ASP Model Studio" icon={<LockKeyhole size={21} />} message={message}>
      <Input label="Email" value={email} onChange={setEmail} />
      <Input label="Password" type="password" value={password} onChange={setPassword} />
      <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700">
        <input type="checkbox" checked={keepSignedIn} onChange={(event) => setKeepSignedIn(event.target.checked)} />
        Keep me Signed In
      </label>
      <button onClick={submit} className="w-full rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">Sign In</button>
      <p className="text-center text-sm leading-6 text-slate-500">Access is provisioned by a workspace administrator. Public registration is disabled.</p>
    </AuthShell>
  );
}

export function RegisterPage({ onAuthenticated }: AuthPageProps = {}) {
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");

  async function submit() {
    setMessage("");
    if (password !== confirmPassword) {
      setMessage("Passwords do not match.");
      return;
    }
    try {
      const response = await register(email, displayName, password);
      onAuthenticated?.(response.user);
      const returnTo = safeAuthReturnPath(new URLSearchParams(location.search).get("returnTo"));
      navigate(returnTo || "/dashboard", { replace: true });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ASP Model Studio could not create this account.");
    }
  }

  return (
    <AuthShell title="Create ASP Model Studio Account" icon={<UserPlus size={21} />} message={message}>
      <Input label="Display Name" value={displayName} onChange={setDisplayName} />
      <Input label="Email" value={email} onChange={setEmail} />
      <Input label="Password" type="password" value={password} onChange={setPassword} helper="Use at least 8 characters. Longer passphrases are recommended." />
      <Input label="Confirm Password" type="password" value={confirmPassword} onChange={setConfirmPassword} />
      <button onClick={submit} className="w-full rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">Create Account</button>
      <p className="text-center text-sm text-slate-600">Already have an account? <Link to="/login" className="font-semibold text-blue-700">Sign in</Link></p>
    </AuthShell>
  );
}

export function AccountPage() {
  const navigate = useNavigate();
  const projectId = useWorkflowStore((state) => state.projectId);
  const [user, setUser] = useState<AtlasUser | null>(null);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [projectDatasets, setProjectDatasets] = useState<ProjectDatasetLink[]>([]);
  const [projectCount, setProjectCount] = useState(0);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");

  async function refresh() {
    try {
      const auth = await me();
      setUser(auth.user);
      setDatasets((await listDatasets()).datasets);
      setProjectDatasets(await listProjectDatasets(projectId));
      setProjectCount(loadLocalProjects().length);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ASP Model Studio account details are unavailable.");
    }
  }

  useEffect(() => {
    refresh();
  }, [projectId]);

  return (
    <div className="w-full space-y-5">
      <Header title="Account" icon={<ShieldCheck size={21} />} description="Your ASP Model Studio identity, role, owned assets, shared assets, and password controls." />
      {message && <Banner message={message} />}
      <section className="grid gap-4 md:grid-cols-4">
        <Metric label="Display Name" value={user?.displayName ?? "-"} />
        <Metric label="Email" value={user?.email ?? "-"} />
        <Metric label="Role" value={user?.role ?? "-"} />
        <Metric label="Status" value={user?.status ?? "-"} />
      </section>
      <Card title="Account Test Checklist">
        <ChecklistRow label="You are signed in as" value={user?.displayName ?? "-"} />
        <ChecklistRow label="User ID" value={user?.userId ?? "-"} />
        <ChecklistRow label="Role" value={user?.role ?? "-"} />
        <ChecklistRow label="Session" value={user ? "Active" : "Not active"} />
        <ChecklistRow label="Dataset access" value={`${datasets.length} visible dataset${datasets.length === 1 ? "" : "s"}`} />
        <ChecklistRow label="Project access" value={`${projectCount} visible browser project${projectCount === 1 ? "" : "s"}`} />
      </Card>
      <section className="grid gap-5 xl:grid-cols-2">
        <Card title="Change Password">
          <Input label="Current Password" type="password" value={currentPassword} onChange={setCurrentPassword} />
          <Input label="New Password" type="password" value={newPassword} onChange={setNewPassword} />
          <button
            onClick={async () => {
              try {
                await changePassword(currentPassword, newPassword);
                setMessage("Password changed.");
                setCurrentPassword("");
                setNewPassword("");
              } catch (error) {
                setMessage(error instanceof Error ? error.message : "Password could not be changed.");
              }
            }}
            className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white"
          >
            Change Password
          </button>
        </Card>
        <Card title="Session">
          <button
            onClick={async () => {
              await logout();
              // Clear only the ambient selected-workflow view. Durable project
              // records remain in the authorized backend registry.
              useWorkflowStore.getState().reset();
              navigate("/login");
            }}
            className="inline-flex w-fit items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-semibold text-red-700 hover:bg-red-50"
          >
            <LogOut size={15} />
            Sign Out
          </button>
        </Card>
      </section>
      <section className="grid gap-5 xl:grid-cols-2">
        <Card title="Accessible Datasets">
          <AssetList items={datasets.map((dataset) => `${dataset.name} · ${dataset.ownerUserId === user?.userId ? "owned" : "shared"} · ${dataset.latestVersion?.rowCount?.toLocaleString() ?? "-"} rows`)} empty="No accessible datasets." />
        </Card>
        <Card title="Current Project Dataset Links">
          <AssetList items={projectDatasets.map((link) => `${link.dataset?.name || link.datasetId} · ${link.datasetRole} · ${link.versionId}`)} empty="No project datasets linked." />
        </Card>
      </section>
    </div>
  );
}

export function AdminUsersPage() {
  const [users, setUsers] = useState<AtlasUser[]>([]);
  const [newUser, setNewUser] = useState({ email: "", displayName: "", password: "", role: "data_scientist" });
  const [message, setMessage] = useState("");

  async function refresh() {
    try {
      setUsers((await adminUsers()).users);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Admin users are unavailable.");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="w-full space-y-5">
      <Header title="User Administration" icon={<Users size={21} />} description="Admin-only ASP Model Studio user management for local authentication, role assignment, status controls, and lockout remediation." />
      {message && <Banner message={message} />}
      <Card title="Create User">
        <p className="mb-3 text-sm text-slate-600">
          The selected role changes this user&apos;s permissions. ASP Model Studio records the signed-in administrator,
          selected role, and outcome in the security audit trail.
        </p>
        <div className="grid gap-3 lg:grid-cols-4">
          <Input label="Display Name" value={newUser.displayName} onChange={(value) => setNewUser({ ...newUser, displayName: value })} />
          <Input label="Email" value={newUser.email} onChange={(value) => setNewUser({ ...newUser, email: value })} />
          <Input label="Password" type="password" value={newUser.password} onChange={(value) => setNewUser({ ...newUser, password: value })} />
          <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Role
            <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={newUser.role} onChange={(event) => setNewUser({ ...newUser, role: event.target.value })}>
              {roles.map((role) => <option key={role} value={role}>{role}</option>)}
            </select>
          </label>
        </div>
        <button
          onClick={async () => {
            try {
              await adminCreateUser(newUser);
              setNewUser({ email: "", displayName: "", password: "", role: "data_scientist" });
              await refresh();
            } catch (error) {
              setMessage(error instanceof Error ? error.message : "ASP Model Studio could not create this user.");
            }
          }}
          className="mt-3 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white"
        >
          Create User
        </button>
      </Card>
      <Card title="Users">
        <div className="overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2 text-left">User</th><th className="px-3 py-2 text-left">Email</th><th className="px-3 py-2">Role</th><th className="px-3 py-2">Status</th><th className="px-3 py-2 text-left">Created</th><th className="px-3 py-2 text-left">Last active</th><th className="px-3 py-2">Projects</th><th className="px-3 py-2">Evidence</th><th className="px-3 py-2">Validations</th><th className="px-3 py-2">Exports</th><th className="px-3 py-2">Failed</th><th className="px-3 py-2 text-left">Actions</th></tr>
            </thead>
            <tbody>
              {users.map((user) => (
                <tr key={user.userId} className="border-t">
                  <td className="px-3 py-2 font-semibold">{user.displayName}</td>
                  <td className="px-3 py-2">{user.email}</td>
                  <td className="px-3 py-2">
                    <select className="rounded border px-2 py-1" value={user.role} onChange={async (event) => { await adminSetRole(user.userId, event.target.value); await refresh(); }}>
                      {roles.map((role) => <option key={role} value={role}>{role}</option>)}
                    </select>
                  </td>
                  <td className="px-3 py-2">{user.status}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs">{formatTimestamp(user.createdAt)}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-xs">{formatTimestamp(user.lastActiveAt || user.lastLoginAt)}</td>
                  <td className="px-3 py-2 text-center">{user.projectCount ?? 0}</td>
                  <td className="px-3 py-2 text-center">{user.evidenceCount ?? 0}</td>
                  <td className="px-3 py-2 text-center">{user.validationCount ?? 0}</td>
                  <td className="px-3 py-2 text-center">{user.exportCount ?? 0}</td>
                  <td className="px-3 py-2 text-center">{user.failedLoginCount ?? 0}</td>
                  <td className="space-x-2 px-3 py-2">
                    {user.status !== "active" ? <button className="rounded border px-2 py-1" onClick={async () => { await adminEnableUser(user.userId); await refresh(); }}>Activate</button> : <button className="rounded border px-2 py-1" onClick={async () => { await adminDisableUser(user.userId); await refresh(); }}>Set inactive</button>}
                    <button className="rounded border px-2 py-1" onClick={async () => { await adminUnlockUser(user.userId); await refresh(); }}>Unlock</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

export function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [filters, setFilters] = useState({ projectId: "", resourceType: "", resourceId: "", actionType: "", userId: "", text: "", dateFrom: "", dateTo: "", sharingOnly: false, adminOnly: false });
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [message, setMessage] = useState("");

  async function refresh() {
    try {
      setEvents((await searchAuditLog(filters)).events);
    } catch (error) {
      try {
        setEvents((await auditEvents({ projectId: filters.projectId, resourceType: filters.resourceType, action: filters.actionType, userId: filters.userId })).events.map((event) => ({
          audit_id: String(event.auditId ?? crypto.randomUUID()),
          created_at: String(event.timestamp ?? ""),
          project_id: String(event.projectId ?? ""),
          user_id: String(event.userId ?? ""),
          action_type: String(event.action ?? ""),
          entity_type: String(event.resourceType ?? ""),
          entity_id: String(event.resourceId ?? ""),
          summary: String(event.reason ?? ""),
        })));
      } catch {
        setMessage(error instanceof Error ? error.message : "Audit events are unavailable.");
      }
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  return (
    <div className="w-full space-y-5">
      <Header title="Audit Log" icon={<FileClock size={21} />} description="Governance-ready event trail for authentication, access, dataset, project, model, report, diagnostics, and denied-access actions." />
      {message && <Banner message={message} />}
      <Card title="Filters">
        <div className="grid gap-3 md:grid-cols-4 xl:grid-cols-8">
          <Input label="Project ID" value={filters.projectId} onChange={(value) => setFilters({ ...filters, projectId: value })} />
          <Input label="User ID" value={filters.userId} onChange={(value) => setFilters({ ...filters, userId: value })} />
          <Input label="Action Type" value={filters.actionType} onChange={(value) => setFilters({ ...filters, actionType: value })} />
          <Input label="Resource Type" value={filters.resourceType} onChange={(value) => setFilters({ ...filters, resourceType: value })} />
          <Input label="Resource ID" value={filters.resourceId} onChange={(value) => setFilters({ ...filters, resourceId: value })} />
          <Input label="Text Search" value={filters.text} onChange={(value) => setFilters({ ...filters, text: value })} />
          <Input label="Date From" type="date" value={filters.dateFrom} onChange={(value) => setFilters({ ...filters, dateFrom: value })} />
          <Input label="Date To" type="date" value={filters.dateTo} onChange={(value) => setFilters({ ...filters, dateTo: value })} />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700"><input type="checkbox" checked={filters.sharingOnly} onChange={(event) => setFilters({ ...filters, sharingOnly: event.target.checked })} /> Permission and sharing events only</label>
          <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700"><input type="checkbox" checked={filters.adminOnly} onChange={(event) => setFilters({ ...filters, adminOnly: event.target.checked })} /> Admin actions only</label>
          <button onClick={refresh} className="self-end rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white">Apply</button>
          <a className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700" href={auditExportUrl("csv", filters)}>Export filtered audit log CSV</a>
          <a className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700" href={auditExportUrl("json", filters)}>Export filtered audit log JSON</a>
        </div>
      </Card>
      <Card title="Events">
        <div className="overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2 text-left">Timestamp</th><th className="px-3 py-2 text-left">Actor</th><th className="px-3 py-2 text-left">Action type</th><th className="px-3 py-2 text-left">Resource</th><th className="px-3 py-2 text-left">Project</th><th className="px-3 py-2 text-left">Summary</th><th className="px-3 py-2 text-left">Actions</th></tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={event.audit_id} className="border-t">
                  <td className="whitespace-nowrap px-3 py-2">{formatTimestamp(event.created_at)}</td>
                  <td className="px-3 py-2">{event.user_id || "-"}</td>
                  <td className="px-3 py-2 font-semibold">{event.action_type}</td>
                  <td className="px-3 py-2">{event.entity_type || ""} / {event.entity_id || "-"}</td>
                  <td className="px-3 py-2">{event.project_id || "-"}</td>
                  <td className="px-3 py-2">{event.summary || event.title || ""}</td>
                  <td className="px-3 py-2"><button className="rounded border border-slate-300 px-2 py-1 text-xs font-semibold" onClick={() => setSelected(event)}>View details</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      {selected && (
        <Card title="Audit Detail Drawer">
          <div className="grid gap-3 md:grid-cols-3">
            <Metric label="Actor" value={selected.user_id || "Not recorded"} />
            <Metric label="Action" value={selected.action_type} />
            <Metric label="Resource" value={`${selected.entity_type || "resource"} / ${selected.entity_id || "-"}`} />
          </div>
          <pre className="max-h-80 overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-slate-100">{JSON.stringify(selected, null, 2)}</pre>
          <button className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700" onClick={() => setSelected(null)}>Close details</button>
        </Card>
      )}
    </div>
  );
}

function formatTimestamp(value?: string) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function AuthShell({ title, icon, message, children }: { title: string; icon: React.ReactNode; message: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto grid min-h-[calc(100vh-4rem)] w-full max-w-6xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-[0_28px_80px_rgba(15,23,42,.14)] lg:grid-cols-[1.15fr_.85fr]">
      <section className="sports-hero-panel hidden rounded-none border-0 p-10 text-white lg:flex lg:flex-col lg:justify-between">
        <BrandLogo size="md" variant="dark" showSubtitle />
        <div className="relative z-10 max-w-xl py-10">
          <div className="sports-eyebrow text-cyan-300">Sports model intelligence</div>
          <h2 className="mt-4 text-5xl font-semibold leading-[1.05] tracking-tight">Build the models behind the game.</h2>
          <p className="mt-5 text-base leading-7 text-slate-300">Player state, participation, event and drive models, simulation, temporal validation, calibration, and governed export in one analytical studio.</p>
        </div>
        <div className="relative z-10 grid grid-cols-3 gap-2 text-xs font-semibold text-slate-300">
          {["PLAYER STATE", "GAME SIMULATION", "MODEL GRAPH"].map((label) => <span key={label} className="rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-center">{label}</span>)}
        </div>
      </section>
      <section className="grid place-items-center p-6 sm:p-10">
        <div className="w-full max-w-md">
          <BrandLogo size="md" variant="light" showSubtitle className="mb-8 lg:hidden" />
          <div className="flex items-center gap-3 text-teal-700">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-teal-50">{icon}</span>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-950">{title}</h1>
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-500">Authenticated local access to the isolated sports-model-development workspace.</p>
          <div className="mt-6 grid gap-4">{children}</div>
          {message && <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{message}</div>}
        </div>
      </section>
    </div>
  );
}

function Header({ title, icon, description }: { title: string; icon: React.ReactNode; description: string }) {
  return (
    <section className="rounded-xl border border-slate-200/80 bg-white/90 p-5 shadow-sm">
      <BrandLogo size="md" variant="light" showSubtitle className="mb-3" />
      <div className="flex items-center gap-2">{icon}<h1 className="text-xl font-semibold text-slate-950">{title}</h1></div>
      <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">{description}</p>
    </section>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><h2 className="text-base font-semibold text-slate-950">{title}</h2><div className="mt-4 grid gap-3">{children}</div></section>;
}

function Input({ label, value, onChange, type = "text", helper }: { label: string; value: string; onChange: (value: string) => void; type?: string; helper?: string }) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
      {label}
      <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" type={type} value={value} onChange={(event) => onChange(event.target.value)} />
      {helper && <span className="text-xs font-normal normal-case text-slate-500">{helper}</span>}
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-2 truncate text-lg font-semibold text-slate-950">{value}</div></div>;
}

function AssetList({ items, empty }: { items: string[]; empty: string }) {
  return <div className="grid gap-2">{items.length ? items.map((item) => <div key={item} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">{item}</div>) : <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">{empty}</div>}</div>;
}

function ChecklistRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
      <span className="text-sm font-medium text-slate-600">{label}</span>
      <span className="break-all text-sm font-semibold text-slate-950">{value}</span>
    </div>
  );
}

function Banner({ message }: { message: string }) {
  return <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{message}</div>;
}
