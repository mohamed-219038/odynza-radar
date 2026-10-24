/* Radar strategy plans (version 2) and their content batches, as the API returns them. */
import type { ContentItem, ContentRunSummary, Platform } from "../../types";

export type VoiceKey = "formal" | "friendly" | "funky" | "witty" | "visionary" | "custom";
export interface VoiceOption { key: VoiceKey; label: string; style: string }
export interface Voice { key: VoiceKey; label: string; style: string; language: string }

export interface RadarEvent { date: string; end_date?: string | null; title: string; kind: string; confirmed: boolean; source?: string; campaign_id?: string; channel?: string; note?: string }

export interface RadarDefaults {
  client: { id: number; name: string; audience: string };
  goals: string[];
  budget: number;
  currency: string;
  start_date: string;
  end_date: string;
  voices: Record<Platform, { suggested: VoiceKey; why: string }>;
  voice_options: VoiceOption[];
  languages: Record<Platform, string>;
  paid: string[];
  inputs: { key: string; label: string; count: number; note?: string }[];
  opportunities: { id: number; angle: string; claim: string; confidence: string; expires_on: string }[];
  events: RadarEvent[];
}

export interface RadarPlanSummary {
  plan_id: string;
  company_name: string;
  status: string;
  error?: string | null;
  created_at: string | null;
  objective: string;
  period: { start_date: string | null; end_date: string | null };
  version: 2;
  goal?: string;
  summary?: string;
}

export interface Rival { name: string; tier?: string; positioning?: string; tagline?: string; audience?: string; tone?: string; strengths: string[]; weaknesses: string[]; recent_moves: string[]; threat?: string }
export interface MatrixRow { company: string; tagline: string; target_buyer: string; differentiator: string; tone: string; value_prop: string; you: boolean }
export interface MapPoint { company: string; x: number; y: number; you: boolean }
export interface Gap { topic: string; who: string; action: string }
export interface Campaign {
  id: string; name: string; idea: string; goal: string; audience: string; start_date: string; end_date: string;
  budget_percent: number; amount: number | null; channels: string[]; hook: string; hook_ar?: string; key_message: string;
  offer: string; kpi: string; event: string; visual_prompt?: string;
}
export interface Kpi { name: string; stage: string; baseline: string; target: string; target_value?: number | null; unit: string; how: string; cadence: string; campaign_id: string }

export interface RadarPlan {
  version: 2;
  overview: { summary: string; smart_goal: string; big_idea: string; north_star: string; north_star_target: string; highlights: string[] };
  competitive_brief: {
    landscape: string; biggest_opportunity: string; biggest_threat: string; rivals: Rival[]; messaging_matrix: MatrixRow[];
    positioning_map: { x_low: string; x_high: string; y_low: string; y_high: string; points: MapPoint[]; open_space: string };
    content_gaps: Gap[];
    battlecard: { rival: string; their_pitch: string; our_edge: string[]; objections: { they_say: string; we_say: string }[]; landmines: string[] };
  };
  positioning: { statement: string; statement_ar: string; core_message: string; pillars: { name: string; message: string; proof: string }[]; by_platform: { platform: Platform; line: string; language: string; voice: string }[] };
  campaigns: Campaign[];
  calendar: RadarEvent[];
  content_plan: { mix: { label: string; percent: number }[]; rhythm: { platform: Platform; per_week: number; formats: string[]; best_slots: string[]; themes: string[]; voice: string; language: string }[]; gaps: Gap[] };
  budget: { channel: string; percent: number; purpose: string; amount: number | null }[];
  by_month: { month: string; label: string; days: number; amount: number | null; campaigns: string[] }[];
  kpis: Kpi[];
  creative_ideas: { title: string; platform: string; format: string; description: string; why: string }[];
  risks: { risk: string; likelihood: string; mitigation: string }[];
  next_steps: { step: string; owner: string; when: string }[];
  assumptions: string[];
  currency: string;
  budget_monthly: number | null;
  budget_total: number | null;
  notes?: string[];
}

export interface RadarPlanDetail extends RadarPlanSummary {
  inputs: Record<string, unknown> & { goal?: string; voices?: Record<Platform, Voice>; currency?: string; start_date?: string; end_date?: string; budget?: number | null };
  plan: RadarPlan | null;
  validation_errors?: string[];
  visuals: string[];
  logos?: Record<string, string | number>;
}

export interface Rates { spend: number; impressions: number; clicks: number; leads: number; ctr: number | null; cpc: number | null; cpl: number | null; cpm: number | null }
export interface ResultEntry { id: number; week_start: string; platform: string; campaign_id: string; spend: number; impressions: number; clicks: number; leads: number; notes: string }
export interface ResultsReport {
  totals: Rates;
  by_platform: Record<string, Rates>;
  by_campaign: (Rates & { campaign_id: string; name: string })[];
  weeks: (Rates & { week_start: string })[];
  kpis: { name: string; target: string; actual: number | null; state: string | null }[];
  wins: string[];
  misses: string[];
  next_moves: string[];
  currency: string;
  entries: ResultEntry[];
}

export interface AdPlan { name: string; format: string; primary_text: string; headline: string; cta: string; draft_slot_id: string }
export interface AdSet { name: string; audience: string; locations: string[]; ages: string; gender: string; languages: string[]; interests: string[]; job_titles: string[]; placements: string[]; optimization: string; budget_percent: number; amount?: number; daily?: number; ads: AdPlan[] }
export interface MediaBuying {
  summary: string; currency: string; budget: Record<string, number>;
  campaigns: { platform: string; name: string; objective: string; campaign_id: string; budget_percent: number; start_date: string; end_date: string; days: number; bidding: string; amount?: number; daily?: number; ad_sets: AdSet[] }[];
  ab_tests: { name: string; variable: string; a: string; b: string; metric: string; duration: string }[];
  benchmarks: { platform: string; metric: string; range: string; note: string }[];
  checklist: string[];
  tracking: string[];
}

export type RadarItem = ContentItem;
export interface RadarRunDetail extends ContentRunSummary {
  version?: number;
  items: RadarItem[];
  brand_look: string;
  media_buying?: MediaBuying | null;
  voices?: Record<Platform, Voice>;
}
export interface RadarContentDefaults {
  plan_id: string; company_name: string; platforms: Platform[]; version: 2; start_date: string; weeks: number;
  reels_per_month: number; stories_per_week: number; rhythm: Record<Platform, number>; brand_look: string;
  voices: Record<Platform, Voice>; media_buying: boolean; paid_budget: Record<string, number>; currency: string;
}
