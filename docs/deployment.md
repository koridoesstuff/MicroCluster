# Deployment

The app is a single FastAPI process serving `web/` as static files and a
small JSON API. It keeps run state **in memory**, so it needs one
long-running server — it will **not** work on request-scoped serverless
(Vercel / Netlify functions): `POST /api/run` and the follow-up
`GET /api/run/{id}/day/{n}` must hit the same process.

No database. No secrets. No frontend build. `results/*.json` are committed,
so the host never runs `scripts/precompute_results`.

## Recommended host: Render (free tier, least config)

`render.yaml` in the repo root is a complete Blueprint. It installs only
`requirements-runtime.txt` (FastAPI + Uvicorn — the app imports nothing
heavier), pins Python 3.12, and starts
`uvicorn api.app:app --host 0.0.0.0 --port $PORT`.

Free-tier behaviour: the instance sleeps after ~15 min idle and
cold-starts in ~50s. Hit the URL once about a minute before a demo.

### What is already done in the repo
- `render.yaml` — the Blueprint.
- `requirements-runtime.txt` — the two runtime deps.
- `Procfile` — same start command, for hosts that read it (Railway, etc.).
- CORS is already `allow_origins=["*"]`; `Cache-Control: no-cache` is set
  on every non-`/api` response.

### What you need to do manually
1. Create a free account at <https://render.com> (GitHub sign-in is
   fastest).
2. Push this repo to GitHub if it is not there yet.
3. In the Render dashboard: **New → Blueprint**, connect the GitHub repo.
   Render reads `render.yaml` and proposes one service named
   `microcluster`. Click **Apply**.
4. Wait for the first build (~2–3 min) and deploy. Render gives you a URL
   like `https://microcluster.onrender.com`.
5. No environment variables to set — the Blueprint pins `PYTHON_VERSION`
   and nothing else is needed.

### Verify the live URL matches local
- `/` loads the simulator with the sticky limitations bar.
- Run a simulation, play it, drag the resolution slider.
- `/api/results/benchmark`, `/api/results/disclosure_sweep`,
  `/api/results/adversarial` all return the same JSON as local.
- `/terms.html` and `/privacy.html` load.
- `curl -I https://<url>/style.css` shows `cache-control: no-cache`.

## Alternatives (more config, not prepared here)

- **Fly.io** free allowance: needs a `Dockerfile` and `fly.toml` plus the
  `flyctl` CLI. More setup than Render for no benefit here.
- **Hugging Face Spaces** (Docker SDK): free and does not sleep, but needs
  a `Dockerfile` and an `app_port` in the Space README front-matter.

## Deploy status

Not deployed from here — deployment needs an account this environment does
not have. The repo config is complete; the manual steps above are all
that is left.
