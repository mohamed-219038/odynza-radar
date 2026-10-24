/* Shapes returned by the FastAPI backend (see api/routers/*.py). Optional fields may be absent in older rows. */

export interface User {
  id: number;
  username: string;
  role: "admin" | "member" | "viewer" | "client";
}

export interface AuthStatus {
  authenticated: boolean;
  user?: User;
  csrf?: string;
  setup_required?: boolean;
  setup_allowed?: boolean;
  /** approval: new accounts wait for an admin; viewer: new accounts can view at once; off: no sign-up. */
  signup?: "approval" | "viewer" | "off";
}

export interface SourceLink {
  source_id?: string;
  url: string;
  title?: string;
  description?: string;
}

export interface Candidate {
  name: string;
  description?: string;
  reason?: string;
  website?: string;
  facebook?: string;
  instagram?: string;
  linkedin?: string;
  match_type?: string;
  matched_offering?: string;
  customer_overlap?: string;
  market_fit?: string;
  match_evidence?: Record<string, { quote: string; source_id?: string }>;
  sources?: SourceLink[];
  social_found_by_search?: string[];
  social_checks?: Record<string, "on_website" | "matched" | "unconfirmed">;
  social_rejected?: { channel: string; link: string; reason: string }[];
  fit_note?: string;
  rank?: number;
  rank_reason?: string;
  other_websites?: string[];
}

export interface Offering {
  label: string;
  buyer?: string;
  quote?: string;
  source_id?: string;
}

export interface CompanyProfile {
  summary?: string;
  market?: string;
  offerings?: Offering[];
  sources?: SourceLink[];
}

export interface DiscoveryResult {
  candidates?: Candidate[];
  search_results?: SourceLink[];
  company_profile?: CompanyProfile | null;
  cached?: boolean;
  seconds?: number;
  notice?: string;
}

export type DiscoveryEvent =
  | { type: "stage"; message: string }
  | { type: "partial"; candidates: Candidate[]; checking: number; company_profile?: CompanyProfile | null };

export interface Campaign {
  id: string; name: string; start_date: string; end_date: string; channels: string[]; audience: string;
  key_message: string; hypothesis: string; steps: string[]; success_test: string;
}
export interface Kpi { name: string; campaign_id: string; baseline: string; proposed_target: string; measurement: string; cadence: string }

export type Platform = "LinkedIn" | "Instagram" | "Facebook";
export type ItemStatus = "draft" | "approved" | "rejected" | "posted";

export interface ContentRunSummary {
  run_id: string;
  plan_id: string;
  company_name: string;
  status: string;
  error?: string | null;
  created_at: string | null;
  updated_at: string | null;
  platforms: Platform[];
  start_date: string | null;
  end_date: string | null;
  missing_slots: string[];
  counts: Record<ItemStatus, number>;
  total: number;
  version?: number;
}

export interface Slide { headline: string; body: string }

export interface ContentDraft {
  hook?: string;
  text: string;
  hashtags: string[];
  cta?: string;
  language?: string;
  image_prompt?: string;
  on_image_text?: string;
  slides: Slide[];
  higgsfield_prompt?: string;
  reel_seconds?: number | null;
  why?: string;
  checks?: string[];
  campaign_name?: string;
  key_message?: string;
}

export interface ContentItem {
  id: number;
  slot_id: string;
  platform: Platform;
  date: string;
  format: "post" | "carousel" | "document" | "reel" | "story";
  campaign_id: string | null;
  status: ItemStatus;
  content: ContentDraft;
  aspect: string;
  image_status: string;
  image_error?: string | null;
  video_status: string;
  image_url: string | null;
  video_url: string | null;
}

/** An account as an admin sees it on the Team page; "pending" means signed up and waiting for approval. */
export interface ManagedUser {
  id: number;
  username: string;
  role: User["role"] | "pending";
  disabled: boolean;
  created_at: string | null;
  last_login_at: string | null;
}
