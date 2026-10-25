# Odynza Radar

**Watch. Plan. Create. Before they do.**

Odynza Radar is a marketing assistant for one company or several clients. It is built from three agents:

| Agent | What it does |
|---|---|
| **M0 Competitor Intelligence** | Finds your competitors, then keeps watching their websites, Facebook, Instagram, LinkedIn, Meta ads and news. Every change is classified and scored 1 to 5 by impact. Each week it writes a brief (in the app, as a PDF and by email), a claim map and a list of opportunities. |
| **M1 Strategy** | Turns an opportunity, or your own goal, into a full marketing plan: audience, positioning, messages, channels, calendar, budget and KPIs. |
| **M2 Social content** | Writes ready-to-post drafts for LinkedIn, Instagram and Facebook from a plan, with a voice per platform, post images and a media-buying plan. Drafts are approved and posted by hand. |

## How it is built

- **Server:** Python 3.11+, FastAPI, SQLAlchemy with SQLite, Playwright for websites, screenshots and PDFs.
- **Site:** React 19 + TypeScript, built with Vite into `frontend/dist` and served by the same server.
- **AI:** Google Gemini. The heavier reasoning steps (signal scoring, weekly brief, strategy, content) run as three
  [n8n](https://n8n.io) workflows that use built-in nodes only; Radar checks every answer they send back.
- **Data sources:** Serper (Google results), Apify (Facebook, Instagram, LinkedIn, Meta Ad Library), optional Meta
  Business Discovery API, Cloudflare Workers AI (free post images).
- **Accounts:** sign-in is required. Roles are admin, member, viewer and client (a client sees only Competitor watch).
  Sessions, CSRF checks, rate limits and a strict content security policy are built in.

```
api/            FastAPI server (api/main.py), routers, search, strategy and content logic
api/watch/      M0: collectors, change detection, scoring, brief, scheduler
db/             database models
frontend/       React site (src/odynza is the app shell, src/watch the M0 pages)
n8n/            the three n8n workflows to import
scripts/        create_user.py and the CSS generators
tests/          pytest tests (frontend tests live next to the code)
docs/           extra documentation
```

## Run it on your computer

You need Python 3.11 or newer, Node.js 20 or newer, and n8n (for M1, M2 and the M0 scoring).

```bash
# 1. Python side
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# 2. Settings
cp .env.example .env          # Windows: copy .env.example .env
# then open .env and fill in at least GEMINI_API_KEY

# 3. Site
cd frontend
npm install
npm run build
cd ..

# 4. First account (asks for a password)
python scripts/create_user.py yourname --admin

# 5. Start
uvicorn api.main:app --port 8000
```

Open http://localhost:8000 and sign in. The database is created in `data/marketing.db` on first start, and saved
pictures and screenshots go in `data/pictures/`. The server also runs the collection schedule
(`WATCH_SCHEDULER=0` turns it off).

To work on the site with live reload, keep the server running and start `npm run dev` in `frontend/`; Vite sends
the API calls to port 8000.

## Keys you need

Only `GEMINI_API_KEY` is required. Everything else turns on more sources. `.env.example` explains each setting.

| Setting | Used for | Where to get it |
|---|---|---|
| `GEMINI_API_KEY` | search, scoring, plans, content | https://aistudio.google.com/apikey (free tier works) |
| `SERPER_API_KEY` | better company search, "Web & news" source | https://serper.dev |
| `APIFY_API_TOKEN` | Facebook, Instagram, LinkedIn, Meta ads | https://console.apify.com/settings/integrations |
| `OPENROUTER_API_KEY`, `OPENROUTER_IMAGE_MODEL` | better post images (paid, a few cents each; Cloudflare becomes the fallback) | https://openrouter.ai/settings/keys |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | free post images (FLUX.2 on Workers AI; token needs Workers AI permission) | https://dash.cloudflare.com |
| `SMTP_USER`, `SMTP_PASSWORD`, `BRIEF_EMAIL_TO` | weekly brief email (Gmail needs an app password) | your mail provider |

Apify costs credit. `WATCH_APIFY_MONTHLY_USD` sets a monthly budget, and Apify sources pause at 90% of it.

## n8n workflows

Import the three files in [`n8n/`](n8n/README.md), add a Gemini credential to their Gemini nodes, and publish them.
Radar calls them at `http://localhost:5678/webhook/radar-signals`, `radar-weekly`, `radar-strategy` and
`radar-content`. Collection works without n8n; the changes are kept and can be sent for scoring again later.

## Tests

```bash
pytest                      # server tests
cd frontend && npm test     # site tests
```

## Using it from other computers

Add the address people use to `ALLOWED_HOSTS` in `.env` and start the server with `--host 0.0.0.0`. Put it behind
HTTPS (a reverse proxy such as Caddy or nginx) before opening it to the internet, and set `COOKIE_SECURE=1` there.
New people can sign up and wait for an admin to approve them (`SIGNUP_MODE`), or an admin creates their accounts.

## More

- [How fetching and pictures work](docs/HOW_FETCHING_WORKS.md)
- [n8n setup](n8n/README.md)
