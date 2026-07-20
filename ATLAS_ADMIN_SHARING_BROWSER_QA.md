# ATLAS Admin and Sharing Browser QA Checklist

## Startup

1. Start the backend from the repository root:

   `python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload`

2. Start the frontend from the repository root:

   `npm run dev`

3. Open:

   `http://127.0.0.1:5174`

4. Sign in as local admin:

   `admin@atlas.local`

## Admin Console

1. Open `/admin`.
2. Confirm the Admin Console loads.
3. Confirm Users, Groups, Access Requests, Bulk Access, Access Reviews, Ownership Transfer, Permission Audit, and Platform Access Policies are visible.
4. Create a user such as `Demo Analyst` if not already available.
5. Create a group such as `Forecasting Review Team`.
6. Add the user to the group.
7. Confirm the group member count updates.

## Sharing Center

1. Open `/sharing`.
2. Confirm Shared with Me appears.
3. Confirm Shared by Me appears.
4. Confirm Access Requests appears.

## Share Project

1. Open Project Overview.
2. Go to the Access & Sharing panel.
3. Select Share Project.
4. Share with Demo Analyst as View.
5. Confirm Current Access shows the user grant.
6. Confirm Sharing History shows the sharing event.
7. Revoke the share.
8. Confirm Current Access updates.

## Share Dataset

1. Open Dataset Library.
2. Select a real registered dataset row.
3. Select Share Dataset.
4. Share with Forecasting Review Team as Edit.
5. Confirm the regulated-data warning is visible.
6. Confirm expiration options are visible.
7. Confirm group member count is visible.

## Share Evidence

1. Open Model Evidence Center.
2. Select an existing evidence artifact.
3. Select Share Evidence.
4. Confirm the share dialog opens with evidence context.
5. Grant access and confirm the event appears in history.

## Share Documentation

1. Open Model Documentation Studio.
2. Confirm the governed documentation access panel is visible when a document package exists.
3. Select Share Documentation.
4. Grant access and confirm Current Access updates.

## Notification Center

1. Open `/notifications`.
2. Confirm `Notification delivery is local to ATLAS. Email delivery is not enabled.` is visible.
3. Confirm project, dataset, evidence, access request, or ownership notifications appear after the related action.
4. Select Read on one notification.
5. Confirm unread count updates.
6. Select Dismiss on one notification.
7. Confirm it is removed from the default list.

## Access Request

1. Simulate or sign in as a non-admin user.
2. Attempt to open a resource without explicit access where a guarded view is available.
3. Confirm the access-denied state shows requested permission, reason, and Request Access.
4. Submit the request.
5. Return as admin.
6. Open Admin Console and Sharing Center.
7. Confirm the pending request appears.
8. Approve the request.
9. Confirm permission, audit log, sharing event, and notification records are created.

## Audit Log

1. Open `/audit`.
2. Filter by sharing events only.
3. Filter by admin actions only.
4. Search for `resource_shared`.
5. Open an audit detail drawer.
6. Export filtered audit log CSV.
7. Export filtered audit log JSON.
8. Confirm exported content reflects the filtered audit records.

## Access Review

1. Open `/admin`.
2. Create an access review for a project with at least one share.
3. Confirm review items are listed.
4. Mark one permission Keep.
5. Mark one permission Revoke if a safe test share exists.
6. Complete the review.
7. Confirm audit records were written.

## Ownership Transfer

1. Open `/admin`.
2. Use Ownership Transfer on a safe test project or demo resource.
3. Select the new owner.
4. Complete the transfer.
5. Confirm the project owner updates where supported.
6. Confirm notification and audit records are created.

## Bulk Access

1. Open `/admin`.
2. Select a group.
3. Select Projects, Datasets, or Validation cases.
4. Select a permission.
5. Select Preview affected resources.
6. Confirm a nonzero preview count before applying.
7. Select Apply grants only after confirming the preview.
8. Confirm permissions and audit records are created.

## Final Regression Smoke

1. Open `/management-dashboard`.
2. Open `/registry`.
3. Open `/validation`.
4. Open `/datasets`.
5. Open `/model-evidence-center`.
6. Open `/model-document-studio`.
7. Confirm no route crashes and admin visibility remains unrestricted.

