import { useEffect, useState } from "react";
import { Bell, CheckCheck, ExternalLink, X } from "lucide-react";
import { dismissNotification, listNotifications, markAllNotificationsRead, markNotificationRead, type AtlasNotification } from "../lib/adminSharing";

export default function NotificationCenter() {
  const [notifications, setNotifications] = useState<AtlasNotification[]>([]);
  const [message, setMessage] = useState("");

  async function refresh() {
    setMessage("");
    try {
      const payload = await listNotifications();
      setNotifications(payload.notifications);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Notification Center is unavailable.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div className="atlas-page-shell" data-testid="notification-center">
      <section className="rounded-2xl border border-slate-900 bg-slate-950 p-6 text-white shadow-sm">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-sky-200"><Bell size={16} /> Local collaboration</div>
        <h1 className="mt-2 text-2xl font-semibold">Notification Center</h1>
        <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">Notification delivery is local to ATLAS. Email delivery is not enabled.</p>
      </section>

      {message && <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{message}</div>}

      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-slate-950">Collaboration notifications</h2>
            <p className="mt-1 text-sm text-slate-500">Shares, access requests, validation actions, ownership changes, and review reminders appear here.</p>
          </div>
          <button className="atlas-secondary-button" onClick={async () => { await markAllNotificationsRead(); await refresh(); }}>
            <CheckCheck size={16} /> Mark all read
          </button>
        </div>

        <div className="mt-5 grid gap-3">
          {notifications.length ? notifications.map((notification) => (
            <article key={notification.notification_id} className={`rounded-xl border p-4 ${notification.status === "unread" ? "border-blue-200 bg-blue-50" : "border-slate-200 bg-white"}`}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-slate-950">{notification.title}</span>
                    <span className="rounded-full bg-slate-100 px-2 py-1 text-[11px] font-semibold text-slate-600">{notification.notification_type}</span>
                    <span className={`rounded-full px-2 py-1 text-[11px] font-semibold ${notification.priority === "high" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"}`}>{notification.priority}</span>
                  </div>
                  {notification.message && <p className="mt-2 text-sm leading-6 text-slate-600">{notification.message}</p>}
                  <div className="mt-2 text-xs text-slate-500">{formatDate(notification.created_at)} / {notification.resource_type || "platform"} / {notification.resource_id || "no resource"}</div>
                </div>
                <div className="flex shrink-0 gap-2">
                  {notification.resource_type && notification.resource_id && <a className="atlas-secondary-button" href={resourceHref(notification)}><ExternalLink size={15} /> Open</a>}
                  {notification.status === "unread" && <button className="atlas-secondary-button" onClick={async () => { await markNotificationRead(notification.notification_id); await refresh(); }}>Read</button>}
                  <button className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50" onClick={async () => { await dismissNotification(notification.notification_id); await refresh(); }}><X size={15} /></button>
                </div>
              </div>
            </article>
          )) : <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-500">No notifications are waiting for this user.</div>}
        </div>
      </section>
    </div>
  );
}

function resourceHref(notification: AtlasNotification) {
  if (notification.resource_type === "project") return "/project-overview";
  if (notification.resource_type === "dataset") return `/datasets/${encodeURIComponent(notification.resource_id || "")}`;
  if (notification.resource_type === "registry_asset") return `/registry/${encodeURIComponent(notification.resource_id || "")}`;
  if (notification.resource_type === "validation_case") return `/validation/${encodeURIComponent(notification.resource_id || "")}`;
  if (notification.resource_type === "documentation_package") return "/model-document-studio";
  if (notification.resource_type === "evidence_artifact") return "/model-evidence-center";
  return "/sharing";
}

function formatDate(value?: string) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
