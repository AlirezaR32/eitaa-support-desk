/** Shared API types — mirrors backend app/schemas/common.py */

export interface Agent {
  id: number;
  name: string;
  username: string | null;
  email: string;
  role: "owner" | "admin" | "agent" | string;
  is_active: boolean;
  last_login_at: string | null;
  created_at: string;
  permissions: string[];
  eitaa_account_ids: number[];
}

export interface EitaaAccount {
  id: number;
  phone_number: string;
  display_name: string | null;
  username: string | null;
  eitaa_user_id: number | null;
  status: "pending" | "connected" | "disconnected" | "error" | string;
  sync_enabled: boolean;
  last_sync_at: string | null;
  last_sync_ok: boolean | null;
  last_error: string | null;
  agent_ids: number[];
  deep_link: string | null;
}

export interface LoginChallenge {
  challenge_id: string;
  phone_number: string;
  delivery: string;
  next_delivery: string | null;
  timeout_seconds: number | null;
  code_length: number | null;
}

export interface Attachment {
  id: number;
  kind: "photo" | "voice" | "audio" | "video" | "document" | string;
  file_name: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  duration_seconds: number | null;
  width: number | null;
  height: number | null;
  download_status: string;
  download_url: string | null;
}

export interface Message {
  id: number;
  conversation_id: number;
  eitaa_message_id: number | null;
  direction: "inbound" | "outbound";
  source: "sync" | "panel" | "eitaa_app" | string;
  text: string;
  sender_agent_id: number | null;
  sender_agent_name: string | null;
  send_status: "pending" | "sent" | "failed";
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
  reply_to_message_id: number | null;
  reply_preview: string | null;
  attachment: Attachment | null;
}

export interface Note {
  id: number;
  conversation_id: number;
  author_id: number | null;
  author_name: string | null;
  body: string;
  created_at: string;
}

export interface Conversation {
  id: number;
  eitaa_account_id: number;
  eitaa_account_phone: string | null;
  peer_type: string;
  peer_id: number;
  peer_kind: string;
  title: string;
  username: string | null;
  phone: string | null;
  status: "active" | "waiting_user" | "skipped" | "closed" | string;
  read_state: "unread" | "read" | string;
  answer_state: "unanswered" | "answered" | string;
  assigned_agent_id: number | null;
  assigned_agent_name: string | null;
  last_message_at: string | null;
  last_message_preview: string;
  last_inbound_message_at: string | null;
  unread_eitaa_count: number;
  skip_reason: string | null;
  deep_link: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends Conversation {
  first_inbound_at: string | null;
  first_agent_reply_at: string | null;
  closed_at: string | null;
  previous_conversations: Conversation[];
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

export interface Notification {
  id: number;
  type: string;
  conversation_id: number | null;
  title: string;
  body: string;
  is_read: boolean;
  created_at: string;
}

export interface DashboardStats {
  unread: number;
  unanswered: number;
  answered_today: number;
  waiting_user: number;
  skipped: number;
  closed: number;
  my_conversations: number;
  unassigned: number;
  total_conversations: number;
  avg_first_response_seconds: number | null;
  avg_resolution_seconds: number | null;
  messages_today: number;
  active_agents: number;
}

export interface AuditLog {
  id: number;
  actor_id: number | null;
  actor_name: string;
  action: string;
  target_type: string | null;
  target_id: string | null;
  meta: Record<string, unknown> | null;
  ip: string | null;
  created_at: string;
}

export interface Capabilities {
  send_text: boolean;
  send_media: boolean;
  send_voice: boolean;
  receive_media: boolean;
  reply_to: boolean;
  mark_read_best_effort: boolean;
  real_time: boolean;
  sync_interval_seconds: number;
  max_upload_size_mb: number;
  allowed_extensions: string[];
  deep_link_supported: boolean;
}

export interface TokenPair {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: Agent;
}

export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown> };
}
