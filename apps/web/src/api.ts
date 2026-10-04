export interface Agent {
  id: string;
  name: string;
  role?: string;
}
export interface Session {
  user: Agent;
  mode: "demo" | "live";
  sms_ready: boolean;
  voice_ready: boolean;
  email_ready?: boolean;
  bridge_ready?: boolean;
}
export interface Lead {
  id: string;
  name: string;
  phone: string;
  email: string;
  kind: string;
  company?: string;
  mc_number?: string;
  dot_number?: string;
  fleet_size?: number;
  niche?: string;
  city?: string;
  state?: string;
  status: string;
  stage?: string;
  follow_up_at?: string | null;
  last_outcome?: string;
  last_called_at?: string | null;
  last_activity?: string | null;
  last_activity_at?: string | null;
  agent_id: string;
  timezone: string;
  consent_sms: boolean;
  consent_voice: boolean;
  consent_email?: boolean;
  consent_note: string;
  next_followup_at?: string;
  created_at: string;
}
export type Channel = "sms" | "voice" | "email";
export const CHANNEL_NAMES: Record<Channel, string> = {
  sms: "Text message",
  voice: "AI voice call",
  email: "Email",
};
export interface Step {
  channel: Channel;
  delay_minutes: number;
  message: string;
  subject?: string;
}
export interface Template {
  id: string;
  name: string;
  channel: Channel;
  subject: string;
  body: string;
  updated_at: string;
}
export const PLACEHOLDERS =
  "{{first_name}}, {{name}}, {{company}}, {{agent_name}}";
export interface Sequence {
  id: string;
  name: string;
  steps: Step[];
  created_at: string;
}
export interface Activity {
  id: string;
  channel: string;
  direction: string;
  text: string;
  status: string;
  created_at: string;
}
export interface Job {
  id: string;
  channel: string;
  message: string;
  due_at: string;
  status: string;
  error?: string;
}
export interface Detail {
  lead: Lead;
  activities: Activity[];
  jobs: Job[];
  tasks?: Task[];
  enrollment: { id: string; status: string; sequence_id: string } | null;
}
export interface Task {
  id: string;
  lead_id: string;
  title: string;
  due_at: string;
  status: "open" | "done" | "cancelled";
  source: string;
  created_at: string;
  completed_at?: string | null;
  lead_name?: string;
  lead_phone?: string;
}
export const STAGES = [
  "new",
  "contacted",
  "interested",
  "qualified",
  "agreement_sent",
  "onboarded",
  "lost",
] as const;
export const overdue = (task: Task) =>
  task.status === "open" && new Date(task.due_at) < new Date();
export interface Settings {
  automation_enabled: boolean;
  daily_sms_limit: number;
  daily_call_limit: number;
  daily_email_limit?: number;
  contact_start_hour: number;
  contact_end_hour: number;
  mode: string;
}
export const initialLead = {
  name: "",
  phone: "",
  email: "",
  kind: "owner_operator",
  company: "",
  mc_number: "",
  dot_number: "",
  fleet_size: 1,
  niche: "",
  city: "",
  state: "",
  agent_id: "",
  timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  consent_sms: false,
  consent_voice: false,
  consent_email: false,
  consent_note: "",
};
export const validPhone = (phone: string) => /^\+[1-9]\d{7,14}$/.test(phone);
const base =
  (
    import.meta as unknown as { env: { VITE_API_BASE_URL?: string } }
  ).env.VITE_API_BASE_URL?.replace(/\/$/, "") ?? "";
export async function request<T>(
  path: string,
  key: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${base}/api${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${key}`,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new Error(
      "Cannot reach the service. Check your connection and try again.",
    );
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok || !payload?.success)
    throw new Error(
      typeof payload?.error === "string"
        ? payload.error
        : response.status === 401
          ? "Your access key is invalid or expired."
          : `Request failed (${response.status}). Please try again.`,
    );
  return payload.data as T;
}
export const date = (value?: string) =>
  value
    ? new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(new Date(value))
    : "Not scheduled";
export const label = (value: string) => value.replaceAll("_", " ");

export const OUTCOMES: Record<string, string> = {
  connected: "Connected",
  no_answer: "No answer",
  voicemail: "Left voicemail",
  interested: "Interested",
  not_interested: "Not interested",
  wrong_number: "Wrong number",
  call_back: "Call back",
  appointment_set: "Onboarding call set",
};
export const QUEUE_TABS = [
  ["today", "Today"],
  ["untouched", "Untouched"],
  ["followups", "Follow ups"],
  ["in_progress", "In progress"],
  ["closed", "Closed"],
] as const;
export interface QueueData {
  items: Lead[];
  counts: Record<string, number>;
  summary: {
    assigned_today: number;
    called_today: number;
    calls_today: number;
    untouched: number;
    follow_ups_due: number;
  };
}
export const ago = (value?: string | null) => {
  if (!value) return "";
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 1440) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} days ago`;
};
export const KINDS: Record<string, string> = {
  owner_operator: "Owner-operator",
  fleet: "Fleet",
};
export const NICHES = [
  "Dry van",
  "Reefer",
  "Flatbed",
  "Step deck",
  "Car hauler",
  "Hotshot",
  "Box truck",
  "Power only",
  "Tanker",
  "Intermodal",
];
export const place = (lead: Pick<Lead, "city" | "state">) =>
  [lead.city, lead.state].filter(Boolean).join(", ");
export const carrierLine = (lead: Lead) =>
  [
    KINDS[lead.kind] || label(lead.kind),
    lead.niche,
    lead.mc_number && `MC ${lead.mc_number}`,
    place(lead),
  ]
    .filter(Boolean)
    .join(" · ");
