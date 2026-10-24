# How Odynza Radar fetches data and pictures

How the company search, the collectors and the picture store work, and how OpenRouter could be added.

## 1. When you search for a company (Profile > Search by name, and Competitors > Find competitors)

The search runs in `api/discovery.py` and `api/search_pipeline.py`, in this order:

1. **Cache first.** Every answer is kept in the `discovery_cache` table: company profiles for 7 days, homepage reads for 3 days and finished searches for 1 day. The same search twice costs nothing the second time.
2. **Google results through Serper.** Several searches run at the same time through Serper (`SERPER_API_KEY`). Examples are the company name, the name plus "Egypt", the name in Arabic, and the name plus "LinkedIn" or "Facebook". For competitors, the searches use your sector, offer and market instead.
3. **Rules clean the list before any AI is asked.** Directories, news sites, job boards, social sites, articles, duplicates and your own company are removed.
4. **Gemini reads what is left.** One Gemini call, with Google search grounding switched on, picks the real companies and explains why each one fits. The app then checks every answer: links must be public pages, and names must appear on the site.
5. **The websites are read.** Up to 12 homepages are opened to confirm each company and to find its Instagram, Facebook and LinkedIn links. A social link is kept only if that page really belongs to the company.
6. **Results stream to the screen** as each step finishes. That is why you see the list fill in live.

## 2. When Radar collects a rival (Collect tab, Check ads now, and the scheduler)

Each company has **sources**, one per channel. The scheduler inside the Radar server visits direct rivals about every 3.5 days and others weekly. The Collect buttons run a visit now. Each source has its own collector in `api/watch/collect.py`:

| Source | How it is fetched | Cost |
|---|---|---|
| Website pages | A real Chrome (Playwright) opens each page, scrolls down so lazy pictures load, and keeps the HTML | Free |
| Instagram | Meta's own API first (free, via `META_IG_USER_ID`), then Apify's Instagram profile, post and reel scrapers (`WATCH_IG_POSTS`, `WATCH_IG_REELS`) | Free, or Apify credit |
| Facebook | Apify: the page scraper (followers, bio, picture) plus the posts scraper (last 15 posts) | Apify credit |
| LinkedIn | Apify: the company scraper plus the company posts scraper (last 12 posts) | Apify credit |
| Meta ads | Apify actor `jmlp/meta-ad-library-scraper` reading the Meta Ad Library in raw form, keeping only ads run by the watched page | Apify credit (about $0.15 per 1,000 ads) |
| Web and news | Serper news and web search for the last month, without the company's own site | Serper credit |

After each visit:

1. The capture is compared with the last one. Only real changes (a new price, a new ad, a new post, a stopped ad) are saved as changes. Pictures and like counts never count as a change, but they are refreshed every time.
2. The changes go to the n8n workflow, where Gemini classifies them and gives each one a 1 to 5 impact score. The app clamps the scores to the senior-marketer bands.
3. Every Sunday, n8n writes the weekly brief, the claim map and the opportunities.

## 3. How pictures are scraped, and where they are kept

**Where they come from**

- **Website pages:** `api/watch/fields.py` reads every `<img>` (including lazy `data-src` pictures), the `og:image` share picture, the logo in the header and the site's tab icon. Each picture gets a label from clues on the page: alt text, file name, the heading above it and the section it sits in. The label is a type such as "Client logo", "Partner logo", "Product screenshot", "Team" or "Banner". Pictures stay attached to the section of text they sit in.
- **Facebook posts:** the real picture address (`photo_image.uri`, or `thumbnail` for videos), never the photo-page link.
- **Instagram posts:** `media_url`, or `thumbnail_url` for reels, from Meta. From Apify it is `displayUrl` plus `images` for carousels.
- **LinkedIn posts:** the post's full-size picture addresses (`postImages`).
- **Meta ads:** every picture in the ad: images, video preview pictures, and each version (card) of a multi-version ad, up to 10 per ad.
- **Profile pictures and logos:** the account's avatar, and the site's sharpest icon from its web-app manifest, apple-touch icon or `og:logo`.

**Where they are kept**

- The links are saved with each capture in the `watch_snapshots` table (inside `data\marketing.db`).
- The picture files are saved in **`data/pictures/`**. Each file is named by a code made from its link, and a readable copy goes to `data/pictures/library/<company>/<platform>/`. Website screenshots are in `data/pictures/screenshots/<site>/<page>/`. Facebook and Instagram links expire within days, but your copy does not.
- Pictures are saved right after each collection, and again at server start for anything still missing.
- The screens never load pictures from Facebook or Instagram directly. They ask `/watch/image`, which serves your saved copy, or downloads and saves it the first time. Only links that are in your own captures are served.
- **Download everything (.zip)** on All data puts every saved picture in folders per company, together with the data and a CSV.

## 4. OpenRouter: how to use a key, and what it would add

**What it is.** OpenRouter is one account and one API key that reaches hundreds of models from many companies (Gemini, Claude, GPT, Llama, DeepSeek, Qwen and others). They all share one OpenAI-style address, `https://openrouter.ai/api/v1`. You pay per use from prepaid credit. Some models also have a free version (the model name ends in `:free`) with a small daily limit.

**Where Radar uses AI today, and where OpenRouter would plug in**

| Part | Today | With OpenRouter |
|---|---|---|
| n8n workflows (signals, strategy, content) | "Google Gemini Chat Model" node | Swap in n8n's built-in **OpenRouter Chat Model** node. No Code nodes are needed, so your built-in-only rule is kept. |
| Company and competitor search, post images (Python) | Gemini API called directly (`api/gemini.py`) | Needs a small code change: an `LLM_PROVIDER=openrouter` switch that sends the same prompts to OpenRouter |
| Post images (M2) | FLUX on Cloudflare | Unchanged. OpenRouter is mainly for text and reading pictures. |

**How to set it up (n8n part, no code change)**

1. Create the key at openrouter.ai (Settings > Keys). Add a few dollars of credit, or use only `:free` models.
2. In n8n go to Credentials > New > **OpenRouter API** and paste the key there. Never paste it into a workflow file or into a chat.
3. In each workflow, add an **OpenRouter Chat Model** node, pick a model (for example `google/gemini-2.5-flash`, `anthropic/claude-sonnet-4.5` or a `:free` model), connect it where the Gemini node was connected, and Publish.
4. For the Python side, after the switch is built, put `OPENROUTER_API_KEY=...` in your `.env` (only there) and choose models with `OPENROUTER_MODEL`.

**What it would improve**

- **No more Gemini free-tier stops.** When Gemini's free quota runs out, the same request can go to another model automatically. OpenRouter accepts a list of fallback models in one request.
- **Better writing where it matters.** You could use a stronger model only for the strategy plans and the weekly brief, and keep cheap or free models for classifying changes.
- **Labels for every picture.** A model that reads images could write a short label for each scraped picture, such as "Ad: 20% off cloud backup, blue banner". This is the open question from 22 October.
- **Web search on any model.** Adding `:online` to a model name lets it search the web. That would replace Gemini's Google grounding in the competitor search if you move away from Gemini.
- **Cost control.** One dashboard shows the spend per model, and you can set a credit limit on the key.

**Things to know**

- It is not free beyond the `:free` models, and those have low daily limits that suit tests, not daily runs.
- Answers can differ between models. The app already checks every AI answer (scores are clamped and links are verified), so a model swap cannot break the data. The wording may change.
- Google search grounding is a Gemini feature. On other models, use the `:online` search instead.
