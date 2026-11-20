export type Role = "org_admin" | "guard" | "host";

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Me {
  id: string;
  scope: "org" | "platform";
  full_name: string;
  email: string | null;
  phone: string | null;
  roles: (Role | "super_admin")[];
  org: { id: string; name: string; slug: string } | null;
  site_ids: string[];
  whatsapp_enabled?: boolean; // false: no WhatsApp; links are shared by hand, alerts by web push
}

export interface Gate {
  id: string;
  site_id: string;
  name: string;
  qr_token: string;
  qr_rotated_at: string | null;
  is_active: boolean;
  checkin_url: string;
}

export interface Site {
  id: string;
  name: string;
  address: string | null;
  city: string | null;
  state: string | null;
  pincode: string | null;
  map_url: string | null;
  directions_text: string | null;
  safety_contacts: { name: string; phone: string }[];
  is_active: boolean;
  gates: Gate[];
}

export interface Department {
  id: string;
  name: string;
  user_count: number;
}

export interface User {
  id: string;
  full_name: string;
  email: string | null;
  phone: string | null;
  roles: Role[];
  department_id: string | null;
  designation: string | null;
  employee_code: string | null;
  primary_site_id: string | null;
  backup_host_id: string | null;
  is_active: boolean;
  last_login_at: string | null;
  has_password: boolean;
  site_ids: string[];
}

export interface Purpose {
  id: string;
  label: string;
  label_i18n: Record<string, string>;
  requires_id_proof: boolean;
  sort_order: number;
  is_active: boolean;
}

export type FieldType = "text" | "number" | "select" | "checkbox" | "declaration";

export interface CustomField {
  id: string;
  key: string;
  label: string;
  label_i18n: Record<string, string>;
  type: FieldType;
  options: string[];
  required: boolean;
  applies_to: "checkin" | "invite" | "both";
  site_id: string | null;
  sort_order: number;
  is_active: boolean;
}

export interface OrgSettings {
  approval_timeout_min: number;
  max_escalations: number;
  auto_checkout_time: string;
  retention_days: number;
  require_selfie: boolean;
  id_proof_mode: "off" | "optional" | "required";
  store_id_image: boolean;
  guard_manual_requires_otp: boolean;
  verify_visitor_phone: boolean;
  enabled_locales: ("en" | "hi")[];
  privacy_contact: string | null;
}

export interface Org {
  id: string;
  name: string;
  slug: string;
  status: string;
  data_region: string;
  default_locale: string;
  timezone: string;
  branding: { logo_key: string | null; primary_color: string; accent_color: string };
  settings: OrgSettings;
  logo_url: string | null;
}

export interface ImportRow {
  row: number;
  action: "create" | "update" | "skip" | "error";
  full_name: string | null;
  email: string | null;
  phone: string | null;
  errors: string[];
}

export interface ImportResult {
  dry_run: boolean;
  total: number;
  created: number;
  updated: number;
  errors: number;
  new_departments: string[];
  rows: ImportRow[];
}

export interface AuditEntry {
  id: string;
  created_at: string;
  actor_user_id: string | null;
  actor_type: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  diff: Record<string, unknown>;
  ip: string | null;
  actor_name: string | null;
}
