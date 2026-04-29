# Entri Bulk Sharing Links

A small Flask web app that takes a CSV of domains, calls the [Entri Sharing Links API](https://developers.entri.com/api-reference#sharing-links-api) for each one, and returns an XLSX with `Domain | Sharing Link | Status` columns.

The frontend collects everything it needs from the user — applicationId, secret, sharing flow, and the config JSON — so the same deploy works for any number of Entri applications without code changes.

## Self-serve flow

```
Browser ──[applicationId, secret, config JSON, CSV]──▶ Flask /api/generate
                       │
                       ├─ POST /token            (https://api.goentri.com)
                       │   → JWT (cached 55 min for this batch only)
                       │
                       ├─ POST /sharing/{flow}   (one call per domain, JWT reused)
                       │   → { link, job_id }
                       │
                       └─ build XLSX in-memory ──▶ download
```

- Credentials live only in the request that's actively being processed.
- Nothing is persisted, logged in plaintext, or echoed back to the browser.
- Use HTTPS in production (every reasonable hosting platform does this for you).

---

## What the UI looks like

Three steps:

1. **Entri credentials** — applicationId (text) and secret (password input with show/hide).
2. **Sharing config** — flow selector (Connect / Sell) + JSON textarea pre-filled with a working template. Includes "Format JSON" and "Reset to default" helpers; invalid JSON is flagged inline before submit.
3. **Domains CSV** — file picker. One domain per row, with or without a `domain` header.

Submit → XLSX downloads automatically.

---

## Project structure

```
entri-bulk-sharing-links/
├── app.py                  # Flask app, routes, request handling
├── config.py               # Env-var defaults + default config template
├── entri_client.py         # Entri API client (JWT + sharing links)
├── processor.py            # CSV parsing + XLSX building
├── templates/
│   └── index.html          # Self-serve form (3 sections)
├── static/
│   └── style.css
├── requirements.txt
├── Procfile                # Heroku / Render / Railway
├── Dockerfile              # Container deploys (Fly.io, Cloud Run, etc.)
├── runtime.txt             # Python version
├── .env.example            # All env vars now optional
├── .gitignore
├── sample-domains.csv
└── README.md
```

---

## Running locally

```bash
git clone <your-repo-url>.git
cd entri-bulk-sharing-links
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

The app starts at <http://localhost:8000>. Open it in a browser, paste your Entri credentials and config, upload a CSV.

No `.env` file is required for the self-serve flow.

---

## Deployment modes

### A. Multi-tenant / public (recommended)

Deploy without setting `ENTRI_APPLICATION_ID` or `ENTRI_SECRET`. Every visitor brings their own credentials.

### B. Single-tenant (internal tool)

Set `ENTRI_APPLICATION_ID` and `ENTRI_SECRET` as env vars in your hosting platform. They become fallbacks: if a form field is left blank, the env var is used. The form still lets users override on a per-request basis.

If you also want the applicationId pre-filled in the UI, set `ENTRI_PREFILL_APP_ID=true`. **Don't do this on a public deploy** — it would expose your applicationId to anyone who loads the page.

---

## Deploy targets

### Render / Railway / Heroku-style (uses `Procfile`)

1. Push the repo to GitHub.
2. Create a new web service from the repo.
3. Build command: `pip install -r requirements.txt`.
4. Start command: auto-detected from `Procfile`.
5. Optionally set env vars (see `.env.example`).

### Docker (Fly.io, Cloud Run, ECS, any container host)

```bash
docker build -t entri-bulk .
docker run -p 8000:8000 entri-bulk
```

### VPS with systemd

```bash
gunicorn app:app --workers 2 --timeout 120 --bind 0.0.0.0:8000
```

…with nginx or Caddy in front for TLS.

---

## CSV format

One domain per row. A header row named `domain` is optional. Bare URLs (`https://example.com/path`) are accepted — the host is extracted automatically.

```
domain
example.com
mybrand.io
acme.co.uk
```

A starter file is included as `sample-domains.csv`.

---

## Output

The downloaded XLSX has three columns:

| Domain | Sharing Link | Status |
|---|---|---|
| example.com | https://app.goentri.com/share/dd33... | OK |
| bad domain | | ERROR: invalid domain format |
| api-failed.com | | ERROR: /sharing/connect failed (502): ... |

The "Status" column makes partial failures obvious so you can re-run only the rows that need it.

---

## Sharing config

The JSON the user pastes into the form is the inner `config` object documented at <https://developers.entri.com/api-reference#entrishowentriconfig>. The backend wraps it in `{ "applicationId": "...", "config": {...} }` automatically before sending to Entri.

If a user pastes the full request body shape by mistake, the backend detects and unwraps it.

`prefilledDomain` is overwritten with each row from the CSV, so its value in the form is just a placeholder.

---

## Tuning

All knobs are env-var overridable:

| Variable | Default | Purpose |
|---|---|---|
| `ENTRI_APPLICATION_ID` | _empty_ | Server-side fallback if form field is blank |
| `ENTRI_SECRET` | _empty_ | Server-side fallback if form field is blank |
| `ENTRI_PREFILL_APP_ID` | `false` | Pre-fill applicationId in UI from env. **Public deploys: leave false.** |
| `ENTRI_SHARING_FLOW` | `connect` | Default selection in the UI |
| `HTTP_TIMEOUT` | `30` | Per-request timeout to Entri (seconds) |
| `MAX_DOMAINS_PER_REQUEST` | `1000` | Reject CSVs larger than this |
| `MAX_UPLOAD_BYTES` | `2097152` (2 MB) | Reject CSV uploads larger than this |
| `MAX_CONFIG_BYTES` | `65536` (64 KB) | Reject config JSON larger than this |
| `FLASK_DEBUG` | `false` | Never enable in production |

For very large batches, bump the gunicorn `--timeout` in `Procfile` / `Dockerfile` past the default 120s. Calls to Entri are sequential by default; if you need concurrency, parallelize `client.create_sharing_link` inside `processor.process_domains_to_xlsx` with a thread pool (Entri's docs don't publish a strict rate limit — check with their team before fanning out).

---

## Security notes

- The applicationId and secret travel from the user's browser to the backend over HTTPS, get used to mint a JWT and sign sharing-link calls, then are discarded when the request finishes. They are **never** persisted or logged.
- Server logs include the applicationId (a non-sensitive ID) and domain count for traceability, but never the secret or the config JSON.
- `.env` is gitignored. Production env vars come from your hosting platform's secret manager.
- If you stand this up publicly, put it behind some form of access control (basic auth, an SSO proxy, or at least a not-discoverable URL) — otherwise you're offering anyone a way to call the Entri API on whichever applicationId they happen to know. No abuse risk for *you*, but it's polite to gate it.

---

## Troubleshooting

**"Missing credentials" / 400** — the applicationId or secret field is blank and no env-var fallback is set.

**"Failed to authenticate with Entri" / 502** — verify your applicationId and secret in the [Entri Dashboard](https://dashboard.goentri.com).

**"Could not parse config JSON" / 400** — the textarea contains invalid JSON. Use the **Format JSON** button to spot the problem; the error message includes the line and column.

**`userId Mismatch`** — see <https://developers.entri.com/errors/overview#userid-mismatch>. If you set a `userId` in your config, make sure it matches the one used when the JWT was minted.

**Some domains succeed, some fail** — the per-row error in the `Status` column is the response body from Entri. Common causes: invalid domain format, provider not supported, or transient API errors. Re-run only those rows by editing your CSV.
