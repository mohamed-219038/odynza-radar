# n8n workflows

Radar sends its AI-heavy steps to three n8n workflows. They use built-in n8n nodes only (no Code nodes) and send
their answers back to Radar, which checks every answer before saving it.

| File | Workflow | Webhooks | Does |
|---|---|---|---|
| `radar-signals.json` | Odynza Radar Signals | `radar-signals`, `radar-weekly` | classifies and scores each change after a collection; writes the weekly brief, claim map and opportunity ranking every Sunday |
| `radar-strategy.json` | Odynza Radar Strategy | `radar-strategy` | writes an M1 marketing plan |
| `radar-content.json` | Odynza Radar Content | `radar-content` | writes M2 social posts and the media-buying plan |

## Set up

1. Start n8n (`npx n8n` or Docker). It listens on http://localhost:5678.
2. In n8n: **Overview → Create → Import from file**, once for each JSON file.
3. Open every node named **Gemini** (the signals workflow has two) and pick or create a
   **Google Gemini (PaLM) API** credential with your Gemini key. Keys stay in n8n, never in these files.
4. Press **Publish** (or switch the workflow to Active) so the production webhook URLs work.

## Settings node

Each workflow starts with a **Settings** node:

- `app_base_url`: where n8n reaches Radar. Default `http://127.0.0.1:8000`.
- `radar_token`: leave empty when n8n runs on the same computer as Radar. When n8n runs elsewhere, set
  `N8N_SHARED_TOKEN` in Radar's `.env` and put the same value here.

## Other addresses

If n8n is not at `localhost:5678`, set the full webhook URLs in `.env`: `N8N_SIGNALS_WEBHOOK_URL`,
`N8N_WEEKLY_WEBHOOK_URL`, `N8N_STRATEGY_WEBHOOK_URL` and `N8N_CONTENT_WEBHOOK_URL`.
