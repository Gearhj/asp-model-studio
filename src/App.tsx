import { FormEvent, useEffect, useState } from "react";
import {
  ArrowLeft,
  Bell,
  BriefcaseBusiness,
  CalendarDays,
  Check,
  ChevronRight,
  CirclePlus,
  ClipboardCheck,
  Clock3,
  Command,
  FileText,
  LogOut,
  Mail,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  UserRound,
  UsersRound,
} from "lucide-react";
import ModelingApp from "./apps/ModelingApp";
import StelaDashboardApp from "./apps/StelaDashboardApp";

type Role = "Model Manager" | "Developer" | "Reviewer";
type RiskRank = "RR1" | "RR2" | "RR3" | "RR4";
type ProjectStatus = "On Track" | "At Risk" | "Blocked";

type User = {
  name: string;
  email: string;
  role: Role;
};

type WorkflowStep = {
  id: number;
  title: string;
  details: string[];
  contacts: string[];
  offsetDays: number;
};

type Project = {
  id: string;
  name: string;
  modelId: string;
  businessLine: string;
  manager: string;
  owner: string;
  developers: string[];
  riskRank: RiskRank;
  status: ProjectStatus;
  targetUseDate: string;
  completedSteps: Record<number, string>;
};

const workflowSteps: WorkflowStep[] = [
  {
    id: 1,
    title: "Kick-off meeting with stakeholders",
    details: ["Identify model owner, model manager, developers, reviewers, and launch expectations."],
    contacts: ["Stakeholders", "Development team"],
    offsetDays: 0,
  },
  {
    id: 2,
    title: "Get model ID",
    details: [
      "Request model creation from Model Risk Governance.",
      "Confirm model type, replacement status, target business use date, and intended model use.",
    ],
    contacts: ["CL MRG", "Line-of-business governance"],
    offsetDays: 3,
  },
  {
    id: 3,
    title: "Complete model intake form",
    details: ["Submit the intake package and confirm all intake questions have accountable owners."],
    contacts: ["Model manager", "Governance partner"],
    offsetDays: 3,
  },
  {
    id: 4,
    title: "Finalize MIT form",
    details: [
      "Coordinate required value, finance, model-use, and governance details.",
      "Send finalized materials for governance review and approval.",
    ],
    contacts: ["CL MRG", "Finance", "Model risk officer"],
    offsetDays: 5,
  },
  {
    id: 5,
    title: "Model development",
    details: [
      "Develop the model on the approved platform or document the approved exception path.",
      "Track training data, candidate model decisions, and implementation assumptions.",
    ],
    contacts: ["Model developers", "Data engineering"],
    offsetDays: 10,
  },
  {
    id: 6,
    title: "Attribute submission form",
    details: [
      "Document data attributes and required legal, fair lending, and compliance review.",
      "Capture restrictions, reviewer notes, and sign-off evidence.",
    ],
    contacts: ["Data legal", "Fair lending compliance", "Card compliance"],
    offsetDays: 3,
  },
  {
    id: 7,
    title: "Complete peer review",
    details: ["Complete peer review documentation and upload final peer review evidence."],
    contacts: ["Peer reviewer", "Model manager"],
    offsetDays: 5,
  },
  {
    id: 8,
    title: "Present model to owner and stakeholders",
    details: ["Review model performance, use cases, limitations, and secure approval email."],
    contacts: ["Model owner", "Business stakeholders"],
    offsetDays: 3,
  },
  {
    id: 9,
    title: "Develop MDD",
    details: [
      "Prepare the model development document and AI/ML supplemental material.",
      "Upload MDD, approval notice, code, data access notes, and implementation evidence.",
    ],
    contacts: ["CL MRG", "Validation team"],
    offsetDays: 15,
  },
  {
    id: 10,
    title: "Validation team review",
    details: ["Track validation cycle time by risk rank and respond to findings or restrictions."],
    contacts: ["Validation lead"],
    offsetDays: 45,
  },
  {
    id: 11,
    title: "Update model checks",
    details: ["Complete production checks and document control evidence."],
    contacts: ["Model manager", "Governance partner"],
    offsetDays: 2,
  },
  {
    id: 12,
    title: "Meet with UAT and monitoring teams",
    details: ["Align implementation, UAT, monitoring code, and post-production reporting process."],
    contacts: ["UAT lead", "Monitoring lead"],
    offsetDays: 5,
  },
  {
    id: 13,
    title: "User acceptance testing",
    details: ["Attach UAT results to validation materials and confirm test evidence is complete."],
    contacts: ["UAT lead"],
    offsetDays: 10,
  },
  {
    id: 14,
    title: "Send implementation code",
    details: ["Provide production code, implementation evidence, and any restriction-removal evidence."],
    contacts: ["Implementation lead", "UAT lead"],
    offsetDays: 10,
  },
  {
    id: 15,
    title: "AI SWAT and DUAP",
    details: ["Complete AI governance review and data-use approvals where required."],
    contacts: ["AI governance"],
    offsetDays: 5,
  },
  {
    id: 16,
    title: "Continuous monitoring and reporting",
    details: ["Set monitoring cadence by risk rank and confirm ownership for recurring reporting."],
    contacts: ["Monitoring lead", "Model owner"],
    offsetDays: 10,
  },
];

const seedProjects: Project[] = [
  {
    id: "aurora-card-response",
    name: "Card Response Model",
    modelId: "24891",
    businessLine: "Credit Cards",
    manager: "James Davis",
    owner: "Maya Chen",
    developers: ["Priya Raman", "Leo Park"],
    riskRank: "RR3",
    status: "On Track",
    targetUseDate: "2026-09-18",
    completedSteps: {
      1: "2026-06-04",
      2: "2026-06-07",
      3: "2026-06-10",
      4: "2026-06-14",
      5: "2026-06-22",
      6: "2026-06-23",
    },
  },
  {
    id: "home-equity-retention",
    name: "Home Equity Retention Model",
    modelId: "25114",
    businessLine: "Home Lending",
    manager: "James Davis",
    owner: "Carlos Rivera",
    developers: ["Nora Patel"],
    riskRank: "RR4",
    status: "At Risk",
    targetUseDate: "2026-08-30",
    completedSteps: {
      1: "2026-05-28",
      2: "2026-05-31",
      3: "2026-06-04",
    },
  },
  {
    id: "personal-loan-expansion",
    name: "Personal Loan Expansion Model",
    modelId: "15211",
    businessLine: "Personal Lending",
    manager: "James Davis",
    owner: "Elaine Morgan",
    developers: ["Avery Stone", "Min Kim"],
    riskRank: "RR2",
    status: "Blocked",
    targetUseDate: "2026-11-12",
    completedSteps: {
      1: "2026-06-12",
    },
  },
];

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function addDays(date: string, days: number) {
  const value = new Date(`${date}T00:00:00`);
  value.setDate(value.getDate() + days);
  return value.toISOString().slice(0, 10);
}

function formatDate(value: string) {
  if (!value) return "Not set";
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", year: "numeric" }).format(
    new Date(`${value}T00:00:00`),
  );
}

function getProgress(project: Project) {
  return Math.round((Object.keys(project.completedSteps).length / workflowSteps.length) * 100);
}

function getNextStep(project: Project) {
  return workflowSteps.find((step) => !project.completedSteps[step.id]) ?? workflowSteps[workflowSteps.length - 1];
}

function makeProjectId(name: string) {
  return `${name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "")}-${Date.now()
    .toString()
    .slice(-4)}`;
}

function modelDisplayName(project: Pick<Project, "modelId" | "name">) {
  return `${project.modelId} ${project.name}`;
}

function SchedulingApp() {
  const [user, setUser] = useState<User | null>(() => {
    const stored = localStorage.getItem("modelflow-user");
    return stored ? (JSON.parse(stored) as User) : null;
  });
  const [projects, setProjects] = useState<Project[]>(() => {
    const stored = localStorage.getItem("modelflow-projects");
    return stored ? (JSON.parse(stored) as Project[]) : seedProjects;
  });
  const [selectedId, setSelectedId] = useState(seedProjects[0].id);
  const [showCreate, setShowCreate] = useState(false);
  const [query, setQuery] = useState("");

  const selectedProject = projects.find((project) => project.id === selectedId) ?? projects[0];

  useEffect(() => {
    if (user) {
      localStorage.setItem("modelflow-user", JSON.stringify(user));
    } else {
      localStorage.removeItem("modelflow-user");
    }
  }, [user]);

  useEffect(() => {
    localStorage.setItem("modelflow-projects", JSON.stringify(projects));
  }, [projects]);

  useEffect(() => {
    if (!projects.some((project) => project.id === selectedId) && projects[0]) {
      setSelectedId(projects[0].id);
    }
  }, [projects, selectedId]);

  function updateProject(next: Project) {
    setProjects((current) => current.map((project) => (project.id === next.id ? next : project)));
  }

  if (!user) {
    return <SignIn onSignIn={setUser} />;
  }

  return (
    <div className="app-frame">
      <TopBar user={user} onSignOut={() => setUser(null)} />

      <main className="app-main">
        <section className="manager-panel">
          <ManagerDashboard
            projects={projects}
            query={query}
            selectedId={selectedProject.id}
            onQueryChange={setQuery}
            onSelect={setSelectedId}
            onCreate={() => setShowCreate(true)}
          />
        </section>

        <section className="workflow-panel">
          <ModelWorkflow project={selectedProject} onChange={updateProject} />
        </section>
      </main>

      {showCreate && (
        <CreateProjectModal
          manager={user.name}
          onClose={() => setShowCreate(false)}
          onCreate={(project) => {
            setProjects((current) => [project, ...current]);
            setSelectedId(project.id);
            setShowCreate(false);
          }}
        />
      )}
    </div>
  );
}

function SignIn({ onSignIn }: { onSignIn: (user: User) => void }) {
  const [email, setEmail] = useState("manager@company.com");
  const [name, setName] = useState("James Davis");
  const [role, setRole] = useState<Role>("Model Manager");

  function submit(event: FormEvent) {
    event.preventDefault();
    onSignIn({ name, email, role });
  }

  return (
    <main className="signin-page">
      <section className="signin-visual">
        <div className="brand-lockup">
          <div className="brand-mark">
            <Command size={24} />
          </div>
          <div>
            <strong>ModelFlow</strong>
            <span>Data Science Governance</span>
          </div>
        </div>
        <div className="signin-copy">
          <p>Team workflow command center</p>
          <h1>Track every model from kickoff to monitoring.</h1>
          <span>
            A polished operating layer for model managers, developers, reviewers, and governance
            partners.
          </span>
        </div>
      </section>

      <section className="signin-panel">
        <form onSubmit={submit} className="signin-form">
          <div>
            <p className="eyebrow">Secure workspace</p>
            <h2>Sign in</h2>
          </div>

          <label>
            <span>Name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </label>
          <label>
            <span>Email</span>
            <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          </label>
          <label>
            <span>Role</span>
            <select value={role} onChange={(event) => setRole(event.target.value as Role)}>
              <option>Model Manager</option>
              <option>Developer</option>
              <option>Reviewer</option>
            </select>
          </label>

          <button className="primary-button" type="submit">
            Continue
            <ChevronRight size={16} />
          </button>
        </form>
      </section>
    </main>
  );
}

function TopBar({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  return (
    <header className="topbar">
      <div className="brand-lockup brand-lockup--compact">
        <div className="brand-mark">
          <Command size={19} />
        </div>
        <div>
          <strong>ModelFlow</strong>
          <span>Consumer Lending AI/ML CoE</span>
        </div>
      </div>
      <div className="topbar-actions">
        <button className="icon-button" title="Notifications">
          <Bell size={18} />
        </button>
        <div className="user-chip">
          <UserRound size={16} />
          <span>{user.name}</span>
        </div>
        <button className="ghost-button" onClick={onSignOut}>
          <LogOut size={16} />
          Sign out
        </button>
      </div>
    </header>
  );
}

function ManagerDashboard({
  projects,
  query,
  selectedId,
  onQueryChange,
  onSelect,
  onCreate,
}: {
  projects: Project[];
  query: string;
  selectedId: string;
  onQueryChange: (value: string) => void;
  onSelect: (id: string) => void;
  onCreate: () => void;
}) {
  const filtered = projects.filter((project) =>
    [project.name, project.modelId, project.businessLine, project.owner, project.status]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const averageProgress = Math.round(
    projects.reduce((sum, project) => sum + getProgress(project), 0) / Math.max(projects.length, 1),
  );
  const atRisk = projects.filter((project) => project.status !== "On Track").length;
  const dueSoon = projects.filter((project) => {
    const days = (new Date(project.targetUseDate).getTime() - Date.now()) / 86400000;
    return days <= 60;
  }).length;

  return (
    <div className="dashboard-stack">
      <div className="section-heading">
        <div>
          <p className="eyebrow">Manager dashboard</p>
          <h1>Model portfolio</h1>
        </div>
        <button className="primary-button" onClick={onCreate}>
          <CirclePlus size={17} />
          Create project
        </button>
      </div>

      <div className="metric-grid">
        <Metric icon={<BriefcaseBusiness size={18} />} label="Active models" value={projects.length} />
        <Metric icon={<TrendingUp size={18} />} label="Avg progress" value={`${averageProgress}%`} />
        <Metric icon={<ShieldCheck size={18} />} label="Needs attention" value={atRisk} />
        <Metric icon={<CalendarDays size={18} />} label="Due in 60 days" value={dueSoon} />
      </div>

      <div className="toolbar">
        <Search size={17} />
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder="Search by model, owner, status, or line of business"
        />
      </div>

      <div className="project-list">
        {filtered.map((project) => (
          <button
            key={project.id}
            className={`project-row ${project.id === selectedId ? "project-row--active" : ""}`}
            onClick={() => onSelect(project.id)}
          >
            <div className="project-row__main">
              <strong>{modelDisplayName(project)}</strong>
              <em>Model ID # {project.modelId} · {project.businessLine}</em>
              <span>{project.modelId} · {project.businessLine}</span>
            </div>
            <div className="project-row__meta">
              <StatusPill status={project.status} />
              <span>{getProgress(project)}%</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function ModelWorkflow({ project, onChange }: { project: Project; onChange: (project: Project) => void }) {
  const progress = getProgress(project);
  const kickoffDate = project.completedSteps[1] ?? todayIso();
  const nextStep = getNextStep(project);

  function toggleStep(stepId: number) {
    const completedSteps = { ...project.completedSteps };
    if (completedSteps[stepId]) {
      delete completedSteps[stepId];
    } else {
      completedSteps[stepId] = todayIso();
    }
    onChange({ ...project, completedSteps });
  }

  function updateCompletionDate(stepId: number, value: string) {
    onChange({
      ...project,
      completedSteps: {
        ...project.completedSteps,
        [stepId]: value,
      },
    });
  }

  return (
    <div className="workflow-stack">
      <div className="model-hero">
        <div>
          <button className="back-link">
            <ArrowLeft size={16} />
            Portfolio
          </button>
          <div className="model-id-badge">Model ID # {project.modelId}</div>
          <h2>{modelDisplayName(project)}</h2>
          <div className="model-meta">{project.businessLine} · {project.riskRank}</div>
          <p>{project.modelId} · {project.businessLine} · {project.riskRank}</p>
        </div>
        <StatusPill status={project.status} />
      </div>

      <div className="model-summary">
        <div>
          <span>Model ID #</span>
          <strong>{project.modelId}</strong>
        </div>
        <div>
          <span>Progress</span>
          <strong>{progress}%</strong>
        </div>
        <div>
          <span>Next action</span>
          <strong>{nextStep.title}</strong>
        </div>
        <div>
          <span>Target use date</span>
          <strong>{formatDate(project.targetUseDate)}</strong>
        </div>
        <div>
          <span>Model owner</span>
          <strong>{project.owner}</strong>
        </div>
      </div>

      <div className="completion-strip" aria-label={`${progress}% complete`}>
        {workflowSteps.map((step) => (
          <span
            key={step.id}
            className={project.completedSteps[step.id] ? "completion-strip__done" : ""}
          />
        ))}
      </div>

      <div className="workflow-table">
        <div className="workflow-table__head">
          <span>Done</span>
          <span>Step</span>
          <span>Description</span>
          <span>Contacts</span>
          <span>Completion</span>
          <span>Estimated</span>
        </div>

        {workflowSteps.map((step) => {
          const done = Boolean(project.completedSteps[step.id]);
          return (
            <article key={step.id} className={`workflow-step ${done ? "workflow-step--done" : ""}`}>
              <div>
                <button
                  className={`check-button ${done ? "check-button--done" : ""}`}
                  onClick={() => toggleStep(step.id)}
                  title={done ? "Mark incomplete" : "Mark complete"}
                >
                  {done && <Check size={15} />}
                </button>
              </div>
              <div className="step-number">{step.id}</div>
              <div className="step-copy">
                <strong>{step.title}</strong>
                <ul>
                  {step.details.map((detail) => (
                    <li key={detail}>{detail}</li>
                  ))}
                </ul>
              </div>
              <div className="contact-list">
                {step.contacts.map((contact) => (
                  <span key={contact}>
                    <Mail size={13} />
                    {contact}
                  </span>
                ))}
              </div>
              <div>
                <input
                  className="date-input"
                  type="date"
                  value={project.completedSteps[step.id] ?? ""}
                  onChange={(event) => updateCompletionDate(step.id, event.target.value)}
                />
              </div>
              <div className="estimated-date">{formatDate(addDays(kickoffDate, step.offsetDays))}</div>
            </article>
          );
        })}
      </div>
    </div>
  );
}

function CreateProjectModal({
  manager,
  onClose,
  onCreate,
}: {
  manager: string;
  onClose: () => void;
  onCreate: (project: Project) => void;
}) {
  const [name, setName] = useState("");
  const [modelId, setModelId] = useState("");
  const [businessLine, setBusinessLine] = useState("Credit Cards");
  const [owner, setOwner] = useState("");
  const [developers, setDevelopers] = useState("");
  const [riskRank, setRiskRank] = useState<RiskRank>("RR3");
  const [targetUseDate, setTargetUseDate] = useState("2026-10-15");

  function submit(event: FormEvent) {
    event.preventDefault();
    const project: Project = {
      id: makeProjectId(name),
      name,
      modelId,
      businessLine,
      manager,
      owner,
      developers: developers.split(",").map((developer) => developer.trim()).filter(Boolean),
      riskRank,
      status: "On Track",
      targetUseDate,
      completedSteps: {},
    };
    onCreate(project);
  }

  return (
    <div className="modal-backdrop" role="dialog" aria-modal="true">
      <form className="modal-card" onSubmit={submit}>
        <div className="section-heading">
          <div>
            <p className="eyebrow">New model</p>
            <h2>Create project</h2>
          </div>
          <button type="button" className="ghost-button" onClick={onClose}>
            Close
          </button>
        </div>

        <div className="form-grid">
          <label>
            <span>Project name</span>
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </label>
          <label>
            <span>Model ID #</span>
            <input
              value={modelId}
              onChange={(event) => setModelId(event.target.value)}
              placeholder="15211"
              required
            />
          </label>
          <label>
            <span>Business line</span>
            <select value={businessLine} onChange={(event) => setBusinessLine(event.target.value)}>
              <option>Credit Cards</option>
              <option>Home Lending</option>
              <option>Personal Lending</option>
              <option>Auto Lending</option>
            </select>
          </label>
          <label>
            <span>Model owner</span>
            <input value={owner} onChange={(event) => setOwner(event.target.value)} required />
          </label>
          <label>
            <span>Risk rank</span>
            <select value={riskRank} onChange={(event) => setRiskRank(event.target.value as RiskRank)}>
              <option>RR1</option>
              <option>RR2</option>
              <option>RR3</option>
              <option>RR4</option>
            </select>
          </label>
          <label className="form-grid__wide">
            <span>Developers</span>
            <input
              value={developers}
              onChange={(event) => setDevelopers(event.target.value)}
              placeholder="Comma-separated names"
            />
          </label>
          <label>
            <span>Target use date</span>
            <input
              type="date"
              value={targetUseDate}
              onChange={(event) => setTargetUseDate(event.target.value)}
              required
            />
          </label>
        </div>

        <button className="primary-button" type="submit">
          <Sparkles size={16} />
          Create workflow
        </button>
      </form>
    </div>
  );
}

function Metric({ icon, label, value }: { icon: React.ReactNode; label: string; value: string | number }) {
  return (
    <div className="metric-card">
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
      {icon}
    </div>
  );
}

function StatusPill({ status }: { status: ProjectStatus }) {
  return <span className={`status-pill status-pill--${status.toLowerCase().replace(" ", "-")}`}>{status}</span>;
}

export default function App() {
  return import.meta.env.VITE_APP_TARGET === "modeling" ? <ModelingApp /> : <StelaDashboardApp />;
}
