/* Shapes returned by the M0 Watch API (api/routers/watch.py). */

export type Tier = "direct" | "adjacent" | "aspirational" | "emerging";
export type SocialKind = "instagram" | "facebook" | "linkedin";
export type Socials = Partial<Record<SocialKind, string>>;

export interface Budget {
  month: string;
  spent_usd: number;
  limit_usd: number;
  paused: boolean;
  per_run_usd: number;
}

export interface WatchClient {
  id: number;
  name: string;
  website: string;
  sector: string;
  market: string;
  offer: string;
  audience: string;
  positioning: string;
  price_position: "budget" | "mid" | "premium";
  channels: string[];
  claims: string[];
  socials: Socials;
  brief_emails: string[];
  version: number;
  updated_at: string | null;
  /** Non-zero when the client chose its own logo; changes the logo links so browsers fetch it again. */
}

export interface ClientInfo {
  client: WatchClient | null;
  starter_claims: string[];
  tiers: Tier[];
  page_kinds: string[];
  email_ready: boolean;
  budget: Budget;
  counts?: Record<"proposed" | "confirmed" | "rejected" | "queued", number>;
  own_sources?: number;
  progress?: Progress;
  clients?: { id: number; name: string; website: string }[];
  logins?: string[];
}

export interface Progress {
  confirmed: number;
  captures: number;
  repeated?: number;
  collections: number;
  running: { id: number; done: number; total: number } | null;
  scoring: number;
  changes: number;
  signals: number;
  briefs: number;
  opportunities: number;
}

export interface Competitor {
  id: number;
  name: string;
  website: string;
  socials: Socials;
  tier: Tier;
  status: "proposed" | "confirmed" | "rejected" | "queued";
  origin: string;
  why: string;
  decided_by: string | null;
  decided_at: string | null;
  review_at: string | null;
  review_due: boolean;
  created_at: string | null;
  sources?: number;
}

export interface Evidence {
  field: string;
  kind: string;
  before: string | null;
  after: string | null;
  before_snapshot_id: number | null;
  after_snapshot_id: number | null;
  before_at?: string | null;
  after_at?: string | null;
}

export interface Signal {
  id: number;
  competitor_id: number | null;
  competitor: string;
  type: string;
  theme: string;
  title: string;
  meaning: string;
  claims: string[];
  source_url: string;
  captured_at: string | null;
  created_at: string | null;
  score: number | null;
  ai_score: number | null;
  reason: string;
  corrected: boolean;
  corrected_by: string | null;
  evidence?: Evidence;
}

export interface Alert {
  id?: number;
  rule: string;
  message: string;
  competitor?: string | null;
  at: string | null;
}

export interface PlatformStats {
  followers: number | null;
  engagement_rate: number | null;
  posts_per_week: number | null;
  posts_30d: number | null;
  days_since_last_post: number | null;
  format_mix: Record<string, number> | null;
  shares_public: boolean | null;
  captured_at?: string | null;
}

export interface ScoreRow {
  key: string;
  id: number | null;
  name: string;
  tier: string;
  you: boolean;
  platforms: Partial<Record<SocialKind, PlatformStats>>;
  live_ads: number | null;
  ads_started_30d: number | null;
}

export interface Overview {
  client: string;
  since: string;
  items: Signal[];
  item_cap: number;
  quiet: boolean;
  watched: number;
  next_check: string | null;
  new_opportunities: number;
  new_entrants: number;
  review_due: number;
  sources: { healthy: number; total: number };
  budget: Budget;
  scorecard: ScoreRow[];
  alerts: Alert[];
  brief?: Brief | null;
  snapshot?: WeekSnapshot;
}

export interface Source {
  id: number;
  company: string;
  competitor_id: number | null;
  kind: "page" | SocialKind | "ads" | "web";
  page_kind: string | null;
  url: string;
  enabled: boolean;
  last_run_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  fail_count: number;
  next_run_at: string | null;
  healthy: boolean;
  via: string;
}

export interface Visit {
  id: number;
  trigger: string;
  status: string;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  changes: number;
}

export interface SourcesInfo {
  sources: Source[];
  healthy: number;
  enabled: number;
  budget: Budget;
  visits: Visit[];
}

export interface PageFields {
  headline?: string;
  headings?: string[];
  buttons?: string[];
  prices?: Record<string, string>;
  services?: string[];
  clients?: string[];
  jobs?: string[];
}

export interface PageCapture {
  source_id: number;
  snapshot_id: number;
  page_kind: string | null;
  url: string;
  captured_at: string | null;
  fields: PageFields;
  previous_fields?: PageFields | null;
  words: number;
  snapshots: number;
  images?: string[];
  pictures?: SitePicture[];
  sections?: { heading: string; text: string; pictures: string[] }[];
  /** "shot:<site>/<page>/<date>.jpg": the whole page as it looked, saved as a JPEG on this computer. */
  screenshot?: string | null;
}

/** One picture found on a website page, labelled from page clues: where it sits, its heading, name and alt text. */
export interface SitePicture {
  url: string;
  kind: "brand_logo" | "client_logo" | "partner_logo" | "logo" | "product" | "team" | "banner" | "other";
  label: string;
  name: string;
  heading: string;
  near: string;
}

export interface Post {
  id: string;
  url: string;
  date: string | null;
  format: string;
  caption: string;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  views: number | null;
  engagement_total: number;
  engagement_rate?: number;
  images?: string[];
}

export interface SocialMetrics extends PlatformStats {
  name?: string | null;
  bio?: string | null;
  avg_engagement?: number;
  hashtags?: string[];
  best_posts?: string[];
  slots?: Record<string, number>;
}

export interface Ad {
  id: string;
  active: boolean;
  start: string | null;
  end: string | null;
  platforms: string[];
  headline: string;
  body: string;
  cta: string;
  landing: string;
  format: string;
  images: string[];
  cards?: { image: string; title: string; body: string; cta: string; link: string }[];
  url: string;
  page_name?: string;
  page_url?: string;
}

export interface Mention {
  id: string;
  url: string;
  kind: "news" | "web";
  title: string;
  snippet: string;
  site: string;
  date: string;
  /** From the article's own share card (Open Graph): its picture, summary, site name and publish date. */
  images?: string[];
  summary?: string;
  site_name?: string;
  published?: string;
}

export interface LogEntry {
  visit_id: number;
  at: string | null;
  kind: string;
  url: string;
  error?: string;
  changes?: number;
  cost?: number;
}

export interface CompetitorDetail {
  competitor: Competitor;
  pages: PageCapture[];
  social: Partial<Record<SocialKind, { them: SocialMetrics; you: SocialMetrics | null; captured_at: string | null; posts: Post[] }>>;
  jobs: string[] | null;
  ads: { items: Ad[]; metrics: Partial<{ live_ads: number; ads_seen: number; page_likes: number | null; started_30d: number; other_pages_dropped: number }>; captured_at: string | null; unchecked?: boolean } | null;
  mentions: { items: Mention[]; captured_at: string | null } | null;
  timeline: Signal[];
  claims: string[];
  log: LogEntry[];
  alerts: Alert[];
  sources: Source[];
}

export interface Gap {
  kind: string;
  label: string;
  rivals: string[];
  detail: string;
}

export interface Claim {
  id: number;
  label: string;
  synonyms: string[];
  holders: Record<string, { quote: string; source_url: string; at: string; by_hand?: boolean }>;
  client_claims: boolean;
  status: "crowded" | "contested" | "unclaimed";
  rival_count: number;
}

export interface CompareData {
  companies: { key: string; id: number | null; name: string; tier: string; you: boolean }[];
  scorecard: { rows: ScoreRow[]; note: string };
  gaps: Gap[];
  claims: Claim[];
}

export interface BriefItem {
  signal_id: number;
  score: number;
  type: string;
  title: string;
  meaning: string;
  move: string;
  source_url: string;
  captured_at: string;
  competitor: string;
}

export interface Brief {
  id: number;
  week_start: string;
  status: "running" | "ready" | "failed" | string;
  headline: string | null;
  items: BriefItem[];
  quiet: boolean;
  error: string | null;
  emailed_at: string | null;
  email_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Opportunity {
  id: number;
  week_start: string;
  rank: number;
  angle: string;
  trigger: string;
  claim: string;
  audience: string;
  why_now: string;
  competitors_saying: string;
  wrong_if: string;
  confidence: "high" | "medium" | "low";
  expires_on: string;
  evidence: string[];
  status: "new" | "accepted" | "rejected" | "acted" | "expired";
  decided_by: string | null;
  plan_id: string | null;
  outcome: string | null;
  created_at: string | null;
  plan_status: string | null;
}

/** What the market did this week, straight from the captures, so a brief is never empty. */
export interface WeekSnapshot {
  as_of: string;
  rivals: { key: string; name: string; tier: Tier; followers: number | null; platform: SocialKind | null; engagement_rate: number | null; posts_7d: number; live_ads: number | null; news: number; jobs: number | null; prices: number | null }[];
  standing: { platform: SocialKind; you: number | null; rivals_avg: number | null; leader: string | null; leader_rate: number | null; you_posts_7d: number | null }[];
  posts: { company: string; key: string; platform: SocialKind; date: string | null; url: string | null; caption: string; likes: number | null; comments: number | null; engagement: number; this_week: boolean }[];
  news: { company: string; title: string | null; site: string | null; date: string | null; url: string | null; kind: string | null }[];
  ads: { company: string; headline: string; body: string; start: string | null; url: string | null }[];
  takeaways: string[];
  numbers: { rivals: number; posts_7d: number; live_ads: number | null; news: number; jobs: number };
}

export interface SavedImage {
  url: string;
  source: string;
  label: string;
  link: string;
  date?: string | null;
  logo?: boolean;
}

/** One company in "All data": the same parts as the competitor detail, plus its pictures. */
export interface CompanyData {
  key: string;
  name: string;
  tier: Tier | "you";
  you: boolean;
  website: string;
  socials: Record<string, string>;
  captured_at: string | null;
  pages: PageCapture[];
  social: CompetitorDetail["social"];
  ads: CompetitorDetail["ads"];
  mentions: CompetitorDetail["mentions"];
  jobs: string[] | null;
  images: SavedImage[];
}
