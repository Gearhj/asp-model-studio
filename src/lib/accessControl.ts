import type { AtlasUser } from "./datasetLibrary";
import type { ResourcePermission } from "./adminSharing";

export const permissionOrder = ["view", "comment", "edit", "validate", "approve", "export", "admin"];

export type AccessControlledResource = {
  resourceType: string;
  resourceId: string;
  ownerUserId?: string;
  createdBy?: string;
  permissionLevel?: string;
  internalDemo?: boolean;
};

export function permissionRank(permission?: string) {
  const index = permissionOrder.indexOf(permission || "view");
  return index >= 0 ? index : 0;
}

export function canUserAccessResource(
  user: AtlasUser | null | undefined,
  resource: AccessControlledResource,
  permission: string = "view",
  explicitPermissions: ResourcePermission[] = [],
) {
  if (!user) return false;
  if (user.role === "admin") return true;
  if (resource.ownerUserId && resource.ownerUserId === user.userId) return true;
  if (resource.createdBy && resource.createdBy === user.userId) return true;
  if (resource.internalDemo) return true;
  const required = permissionRank(permission);
  return explicitPermissions.some((row) => {
    return row.resource_type === resource.resourceType
      && row.resource_id === resource.resourceId
      && row.status === "active"
      && permissionRank(row.permission_level) >= required;
  });
}

export function filterAccessControlledResources<T extends AccessControlledResource>(
  user: AtlasUser | null | undefined,
  resources: T[],
  explicitPermissions: ResourcePermission[] = [],
  permission: string = "view",
) {
  return resources.filter((resource) => canUserAccessResource(user, resource, permission, explicitPermissions));
}

export function accessNotEnforcedDevNote(viewName: string) {
  return `Developer note: access filtering is not yet fully enforced on ${viewName}. Admin visibility remains unrestricted.`;
}
