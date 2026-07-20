import { DATASET_API_BASE, type AtlasUser } from "./datasetLibrary";

async function atlasFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS access request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export const platformRoles = ["admin", "data_scientist", "validator", "manager", "business_owner", "viewer"];
export const permissionLevels = ["view", "comment", "edit", "validate", "approve", "export", "admin"];

export type AdminSummary = {
  totalUsers: number;
  activeUsers: number;
  roleCounts: Record<string, number>;
  groupCount: number;
  pendingAccessRequests: number;
  activeSharedResources: number;
  permissionLevels: string[];
  resourceTypes: string[];
  roleDefinitions: Record<string, string[]>;
};

export type UserGroup = {
  group_id: string;
  group_name: string;
  description?: string;
  status: string;
  memberCount?: number;
};

export type ResourcePermission = {
  permission_id: string;
  resource_type: string;
  resource_id: string;
  principal_type: string;
  principal_id: string;
  permission_level: string;
  granted_by_user_id?: string;
  granted_at: string;
  expires_at?: string;
  status: string;
};

export type SharingEvent = {
  sharing_event_id: string;
  resource_type: string;
  resource_id: string;
  shared_by_user_id: string;
  principal_type: string;
  principal_id: string;
  permission_level: string;
  message?: string;
  created_at: string;
};

export type AccessRequest = {
  request_id: string;
  requester_user_id: string;
  resource_type: string;
  resource_id: string;
  requested_permission: string;
  reason?: string;
  status: string;
  reviewed_by_user_id?: string;
  reviewed_at?: string;
  review_notes?: string;
  created_at: string;
};

export type AtlasNotification = {
  notification_id: string;
  recipient_user_id: string;
  actor_user_id?: string;
  notification_type: string;
  title: string;
  message?: string;
  resource_type?: string;
  resource_id?: string;
  project_id?: string;
  status: string;
  priority: string;
  created_at: string;
  read_at?: string;
  dismissed_at?: string;
  metadata_json?: Record<string, unknown>;
};

export type AuditEvent = {
  audit_id: string;
  project_id?: string;
  user_id?: string;
  action_type: string;
  entity_type?: string;
  entity_id?: string;
  title?: string;
  summary?: string;
  created_at: string;
  metadata_json?: Record<string, unknown>;
};

export type SharingStatus = {
  resourceType: string;
  resourceId: string;
  ownerUserId?: string;
  currentUserPermission: { allowed: boolean; permission: string; reason: string };
  permissions: ResourcePermission[];
  events: SharingEvent[];
  shareLinks: Array<Record<string, unknown>>;
};

export async function getAdminSummary() {
  return atlasFetch<{ ok: true; summary: AdminSummary }>("/admin/summary");
}

export async function listAdminUsers() {
  return atlasFetch<{ ok: true; users: AtlasUser[] }>("/admin/users");
}

export async function createAdminUser(input: { displayName: string; email: string; role: string; status: string }) {
  return atlasFetch<{ ok: true; user: AtlasUser }>("/admin/users", { method: "POST", body: JSON.stringify(input) });
}

export async function updateAdminUserRole(userId: string, role: string) {
  return atlasFetch<{ ok: true; user: AtlasUser }>(`/admin/users/${encodeURIComponent(userId)}/role`, { method: "PUT", body: JSON.stringify({ role }) });
}

export async function updateAdminUserStatus(userId: string, status: string) {
  return atlasFetch<{ ok: true; user: AtlasUser }>(`/admin/users/${encodeURIComponent(userId)}/status`, { method: "PUT", body: JSON.stringify({ status }) });
}

export async function listGroups() {
  return atlasFetch<{ ok: true; groups: UserGroup[] }>("/admin/groups");
}

export async function createGroup(input: { groupName: string; description?: string; status?: string }) {
  return atlasFetch<{ ok: true; group: UserGroup }>("/admin/groups", { method: "POST", body: JSON.stringify(input) });
}

export async function addGroupMember(groupId: string, userId: string, roleInGroup?: string) {
  return atlasFetch<{ ok: true; member: Record<string, unknown> }>(`/admin/groups/${encodeURIComponent(groupId)}/members`, {
    method: "POST",
    body: JSON.stringify({ userId, roleInGroup }),
  });
}

export async function removeGroupMember(groupId: string, userId: string) {
  return atlasFetch<{ ok: true; removed: number }>(`/admin/groups/${encodeURIComponent(groupId)}/members/${encodeURIComponent(userId)}`, { method: "DELETE" });
}

export async function listAccessRequests() {
  return atlasFetch<{ ok: true; requests: AccessRequest[] }>("/admin/access-requests");
}

export async function approveAccessRequest(requestId: string, reviewNotes?: string) {
  return atlasFetch<{ ok: true; request: AccessRequest }>(`/admin/access-requests/${encodeURIComponent(requestId)}/approve`, {
    method: "POST",
    body: JSON.stringify({ reviewNotes }),
  });
}

export async function denyAccessRequest(requestId: string, reviewNotes?: string) {
  return atlasFetch<{ ok: true; request: AccessRequest }>(`/admin/access-requests/${encodeURIComponent(requestId)}/deny`, {
    method: "POST",
    body: JSON.stringify({ reviewNotes }),
  });
}

export async function getSharingStatus(resourceType: string, resourceId: string) {
  return atlasFetch<{ ok: true; sharing: SharingStatus }>(`/sharing/resources/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}`);
}

export async function shareResource(input: {
  resourceType: string;
  resourceId: string;
  principalType: string;
  principalId: string;
  permissionLevel: string;
  message?: string;
  expiresAt?: string;
}) {
  return atlasFetch<{ ok: true; permission: ResourcePermission; event: SharingEvent }>(
    `/sharing/resources/${encodeURIComponent(input.resourceType)}/${encodeURIComponent(input.resourceId)}/share`,
    { method: "POST", body: JSON.stringify(input) },
  );
}

export async function revokeShare(resourceType: string, resourceId: string, principalType: string, principalId: string) {
  return atlasFetch<{ ok: true; revoked: number }>(`/sharing/resources/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}/revoke`, {
    method: "POST",
    body: JSON.stringify({ principalType, principalId }),
  });
}

export async function sharedWithMe() {
  return atlasFetch<{ ok: true; resources: ResourcePermission[] }>("/sharing/shared-with-me");
}

export async function sharedByMe() {
  return atlasFetch<{ ok: true; resources: SharingEvent[] }>("/sharing/shared-by-me");
}

export async function requestAccess(resourceType: string, resourceId: string, requestedPermission = "view", reason = "") {
  return atlasFetch<{ ok: true; request: AccessRequest }>(`/sharing/resources/${encodeURIComponent(resourceType)}/${encodeURIComponent(resourceId)}/request-access`, {
    method: "POST",
    body: JSON.stringify({ requestedPermission, reason }),
  });
}

export async function listNotifications() {
  return atlasFetch<{ ok: true; notifications: AtlasNotification[] }>("/notifications");
}

export async function getUnreadNotificationCount() {
  return atlasFetch<{ ok: true; count: number }>("/notifications/unread-count");
}

export async function markNotificationRead(notificationId: string) {
  return atlasFetch<{ ok: true; notification: AtlasNotification }>(`/notifications/${encodeURIComponent(notificationId)}/read`, { method: "POST" });
}

export async function dismissNotification(notificationId: string) {
  return atlasFetch<{ ok: true; notification: AtlasNotification }>(`/notifications/${encodeURIComponent(notificationId)}/dismiss`, { method: "POST" });
}

export async function markAllNotificationsRead() {
  return atlasFetch<{ ok: true; updated: number }>("/notifications/mark-all-read", { method: "POST" });
}

export async function searchAuditLog(params: Record<string, string | boolean | number | undefined>) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return atlasFetch<{ ok: true; events: AuditEvent[] }>(`/admin/audit-log?${query.toString()}`);
}

export function auditExportUrl(kind: "csv" | "json", params: Record<string, string | boolean | number | undefined> = {}) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== "") query.set(key, String(value));
  });
  return `${DATASET_API_BASE}/admin/audit-log/export.${kind}?${query.toString()}`;
}

export async function listAccessReviews() {
  return atlasFetch<{ ok: true; reviews: Array<Record<string, unknown>> }>("/admin/access-reviews");
}

export async function createAccessReview(input: { reviewName: string; resourceType?: string; resourceId?: string; scope?: string; ownerUserId?: string; dueDate?: string }) {
  return atlasFetch<{ ok: true; review: Record<string, unknown> }>("/admin/access-reviews", { method: "POST", body: JSON.stringify(input) });
}

export async function completeAccessReview(reviewId: string) {
  return atlasFetch<{ ok: true; review: Record<string, unknown> }>(`/admin/access-reviews/${encodeURIComponent(reviewId)}/complete`, { method: "POST" });
}

export async function decideAccessReviewItem(reviewItemId: string, decision: string, reviewerNotes?: string) {
  return atlasFetch<{ ok: true; item: Record<string, unknown> }>(`/admin/access-review-items/${encodeURIComponent(reviewItemId)}/decision`, { method: "POST", body: JSON.stringify({ decision, reviewerNotes }) });
}

export async function listOwnershipTransfers() {
  return atlasFetch<{ ok: true; transfers: Array<Record<string, unknown>> }>("/admin/ownership-transfers");
}

export async function requestOwnershipTransfer(input: { resourceType: string; resourceId: string; toUserId: string; reason?: string }) {
  return atlasFetch<{ ok: true; transfer: Record<string, unknown> }>("/admin/ownership-transfers", { method: "POST", body: JSON.stringify(input) });
}

export async function bulkAccessPreview(input: { groupId: string; resourceType: string; resourceFilter?: string; workflowType?: string; ownerUserId?: string; lifecycleStatus?: string; permissionLevel: string; expiresAt?: string }) {
  return atlasFetch<{ ok: true; preview: { affectedCount: number; resources: Array<{ resourceType: string; resourceId: string; resourceName?: string }> } }>("/admin/bulk-access/preview", { method: "POST", body: JSON.stringify(input) });
}

export async function bulkAccessApply(input: { groupId: string; resourceType: string; resourceFilter?: string; workflowType?: string; ownerUserId?: string; lifecycleStatus?: string; permissionLevel: string; expiresAt?: string; resourceIds?: string[] }) {
  return atlasFetch<{ ok: true; result: { appliedCount: number } }>("/admin/bulk-access/apply", { method: "POST", body: JSON.stringify(input) });
}
