import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
import { useWorkflowStore } from "../state/useWorkflowStore";

const roles = ["admin", "data_steward", "model_owner", "model_manager", "data_scientist", "auditor", "viewer"];

export function LoginPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("admin@atlas.local");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");

  async function submit() {
    setMessage("");
    try {
      await login(email, password);
      navigate("/dashboard");
    } catch {
      setMessage("Sign in failed. Check your email and password.");
    }
  }

  return (
    <AuthShell title="Sign in to ATLAS" icon={<LockKeyhole size={21} />} message={message}>
      <Input label="Email" value={email} onChange={setEmail} />
      <Input label="Password" type="password" value={password} onChange={setPassword} />
      <button onClick={submit} className="w-full rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">Sign In</button>
      <p className="text-center text-sm text-slate-600">Need access? <Link to="/register" className="font-semibold text-blue-700">Create an account</Link></p>
    </AuthShell>
  );
}

export function RegisterPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");

  async function submit() {
    setMessage("");
    try {
      await register(email, displayName, password);
      navigate("/dashboard");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not create this account.");
    }
  }

  return (
    <AuthShell title="Create ATLAS Account" icon={<UserPlus size={21} />} message={message}>
      <Input label="Display Name" value={displayName} onChange={setDisplayName} />
      <Input label="Email" value={email} onChange={setEmail} />
      <Input label="Password" type="password" value={password} onChange={setPassword} helper="Minimum 12 characters. Long passphrases are supported." />
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
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [message, setMessage] = useState("");

  async function refresh() {
    try {
      const auth = await me();
      setUser(auth.user);
      setDatasets((await listDatasets()).datasets);
      setProjectDatasets(await listProjectDatasets(projectId));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS account details are unavailable.");
    }
  }

  useEffect(() => {
    refresh();
  }, [projectId]);

  return (
    <div className="w-full space-y-5">
      <Header title="Account" icon={<ShieldCheck size={21} />} description="Your ATLAS identity, role, owned assets, shared assets, and password controls." />
      {message && <Banner message={message} />}
      <section className="grid gap-4 md:grid-cols-4">
        <Metric label="Display Name" value={user?.displayName ?? "-"} />
        <Metric label="Email" value={user?.email ?? "-"} />
        <Metric label="Role" value={user?.role ?? "-"} />
        <Metric label="Status" value={user?.status ?? "-"} />
      </section>
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
      <Header title="User Administration" icon={<Users size={21} />} description="Admin-only ATLAS user management for local authentication, role assignment, status controls, and lockout remediation." />
      {message && <Banner message={message} />}
      <Card title="Create User">
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
              setMessage(error instanceof Error ? error.message : "ATLAS could not create this user.");
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
              <tr><th className="px-3 py-2 text-left">User</th><th className="px-3 py-2 text-left">Email</th><th className="px-3 py-2">Role</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Failed</th><th className="px-3 py-2 text-left">Actions</th></tr>
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
                  <td className="px-3 py-2 text-center">{user.failedLoginCount ?? 0}</td>
                  <td className="space-x-2 px-3 py-2">
                    {user.status === "disabled" ? <button className="rounded border px-2 py-1" onClick={async () => { await adminEnableUser(user.userId); await refresh(); }}>Enable</button> : <button className="rounded border px-2 py-1" onClick={async () => { await adminDisableUser(user.userId); await refresh(); }}>Disable</button>}
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
  const [events, setEvents] = useState<Array<Record<string, unknown>>>([]);
  const [filters, setFilters] = useState({ resourceType: "", outcome: "", action: "", userId: "" });
  const [message, setMessage] = useState("");

  async function refresh() {
    try {
      setEvents((await auditEvents(filters)).events);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Audit events are unavailable.");
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
        <div className="grid gap-3 md:grid-cols-5">
          <Input label="User ID" value={filters.userId} onChange={(value) => setFilters({ ...filters, userId: value })} />
          <Input label="Action" value={filters.action} onChange={(value) => setFilters({ ...filters, action: value })} />
          <Input label="Resource Type" value={filters.resourceType} onChange={(value) => setFilters({ ...filters, resourceType: value })} />
          <Input label="Outcome" value={filters.outcome} onChange={(value) => setFilters({ ...filters, outcome: value })} />
          <button onClick={refresh} className="self-end rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white">Apply</button>
        </div>
      </Card>
      <Card title="Events">
        <div className="overflow-auto rounded-lg border border-slate-200">
          <table className="min-w-full text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-slate-500">
              <tr><th className="px-3 py-2 text-left">Timestamp</th><th className="px-3 py-2 text-left">User</th><th className="px-3 py-2 text-left">Action</th><th className="px-3 py-2 text-left">Resource</th><th className="px-3 py-2 text-left">Outcome</th><th className="px-3 py-2 text-left">Reason</th></tr>
            </thead>
            <tbody>
              {events.map((event) => (
                <tr key={String(event.auditId)} className="border-t">
                  <td className="whitespace-nowrap px-3 py-2">{String(event.timestamp ?? "")}</td>
                  <td className="px-3 py-2">{String(event.userId ?? "-")}</td>
                  <td className="px-3 py-2 font-semibold">{String(event.action ?? "")}</td>
                  <td className="px-3 py-2">{String(event.resourceType ?? "")} / {String(event.resourceId ?? "-")}</td>
                  <td className="px-3 py-2">{String(event.outcome ?? "")}</td>
                  <td className="px-3 py-2">{String(event.reason ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function AuthShell({ title, icon, message, children }: { title: string; icon: React.ReactNode; message: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto flex min-h-[70vh] max-w-md items-center">
      <section className="w-full rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <BrandLogo size="md" variant="light" showSubtitle className="mb-4" />
        <div className="flex items-center gap-2">
          {icon}
          <h1 className="text-xl font-semibold text-slate-950">{title}</h1>
        </div>
        <div className="mt-5 grid gap-3">{children}</div>
        {message && <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">{message}</div>}
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
      {helper && <span className="text-[11px] font-normal normal-case text-slate-500">{helper}</span>}
    </label>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-2 truncate text-lg font-semibold text-slate-950">{value}</div></div>;
}

function AssetList({ items, empty }: { items: string[]; empty: string }) {
  return <div className="grid gap-2">{items.length ? items.map((item) => <div key={item} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">{item}</div>) : <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">{empty}</div>}</div>;
}

function Banner({ message }: { message: string }) {
  return <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{message}</div>;
}
