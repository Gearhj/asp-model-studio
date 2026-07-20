CREATE TABLE IF NOT EXISTS notifications (
  notification_id TEXT PRIMARY KEY,
  recipient_user_id TEXT NOT NULL,
  actor_user_id TEXT,
  notification_type TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT,
  resource_type TEXT,
  resource_id TEXT,
  project_id TEXT,
  status TEXT NOT NULL DEFAULT 'unread',
  priority TEXT NOT NULL DEFAULT 'normal',
  created_at TEXT NOT NULL,
  read_at TEXT,
  dismissed_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_user_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_resource ON notifications(resource_type, resource_id);

CREATE TABLE IF NOT EXISTS ownership_transfers (
  transfer_id TEXT PRIMARY KEY,
  resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  from_user_id TEXT,
  to_user_id TEXT NOT NULL,
  requested_by_user_id TEXT NOT NULL,
  approved_by_user_id TEXT,
  status TEXT NOT NULL DEFAULT 'pending',
  reason TEXT,
  created_at TEXT NOT NULL,
  approved_at TEXT,
  completed_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_ownership_transfers_resource ON ownership_transfers(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_ownership_transfers_status ON ownership_transfers(status);

CREATE TABLE IF NOT EXISTS access_reviews (
  review_id TEXT PRIMARY KEY,
  review_name TEXT NOT NULL,
  resource_type TEXT,
  resource_id TEXT,
  scope TEXT NOT NULL,
  owner_user_id TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  due_date TEXT,
  created_by_user_id TEXT,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_access_reviews_resource ON access_reviews(resource_type, resource_id);
CREATE INDEX IF NOT EXISTS idx_access_reviews_status ON access_reviews(status);

CREATE TABLE IF NOT EXISTS access_review_items (
  review_item_id TEXT PRIMARY KEY,
  review_id TEXT NOT NULL REFERENCES access_reviews(review_id) ON DELETE CASCADE,
  resource_type TEXT NOT NULL,
  resource_id TEXT NOT NULL,
  principal_type TEXT NOT NULL,
  principal_id TEXT NOT NULL,
  permission_level TEXT NOT NULL,
  decision TEXT NOT NULL DEFAULT 'pending',
  reviewer_user_id TEXT,
  reviewer_notes TEXT,
  decided_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_access_review_items_review ON access_review_items(review_id);
CREATE INDEX IF NOT EXISTS idx_access_review_items_decision ON access_review_items(decision);
