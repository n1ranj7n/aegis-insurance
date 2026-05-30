# Aegis — Health Insurance Platform

A deployable, production-shaped **health insurance management platform** built with
Django and PostgreSQL. It manages policyholders, policies, and claims, and ships
with a **dynamic No-Claim-Bonus (NCB) premium engine** that rewards claim-free
renewal periods with tiered discounts.

This is a portfolio/demo project designed to be deployed publicly, so it includes
real demo-safety features: a nightly data reset, per-table row caps, per-IP write
rate limiting, and input validation.

- **Stack:** Django 5.2 (LTS), PostgreSQL (Neon-ready), Gunicorn, WhiteNoise
- **Config:** 100% environment-driven (`.env` locally, real env vars in prod)
- **Deploy:** Render / Railway — no extra infrastructure required

---

## Table of contents

- [Features](#features)
- [Demo login](#demo-login)
- [Quick start (local)](#quick-start-local)
- [Connecting to Neon PostgreSQL](#connecting-to-neon-postgresql)
- [The premium engine in 30 seconds](#the-premium-engine-in-30-seconds)
- [Management commands](#management-commands)
- [Deploying to Render](#deploying-to-render)
- [Scheduling the nightly reset](#scheduling-the-nightly-reset)
- [Environment variables](#environment-variables)
- [Running the tests](#running-the-tests)
- [Project structure](#project-structure)

---

## Features

- **Dashboard** — KPI cards (policyholders, active policies, claims, premium pool,
  average NCB discount) plus a claims-by-type doughnut and a premium-discount
  distribution bar chart (Chart.js via CDN).
- **Policyholders / Policies / Claims** — full list + detail pages, with forms to
  create and edit records directly from the UI (not just the admin).
- **Dynamic premium engine** — No-Claim-Bonus recalculation exposed three ways:
  a dashboard **Run Renewal** button, a Django admin action, and a management
  command — so the logic is demonstrable instantly.
- **Append-only premium history** — every recalculation writes an audit row.
- **Django admin** — all models registered with rich `list_display`, filters,
  search, inlines, and the Run-Renewal action.
- **Demo-safety** — nightly reset, configurable row caps, per-IP write throttling,
  and validation that rejects absurd values (negative premiums, claims above the
  sum insured, etc.).

## Demo login

```
username: demo
password: demo1234
```

The credentials are shown on the login page and the demo user is (re)created by the
seed/reset commands. They can be changed via `DEMO_USERNAME` / `DEMO_PASSWORD`.

---

## Quick start (local)

**Prerequisites:** Python 3.12, a PostgreSQL database URL (a free [Neon](https://neon.tech)
database works perfectly).

```bash
# 1. Create and activate a virtual environment
python -m venv venv
# Windows (PowerShell):
venv\Scripts\Activate.ps1
# macOS / Linux:
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env        # then edit .env — at minimum set DATABASE_URL
#   Generate a SECRET_KEY:
#   python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"

# 4. Create the schema
python manage.py migrate

# 5. Seed realistic demo data (15 holders, 20 policies, 25 claims) + demo user
python manage.py seed_demo

# 6. Run it
python manage.py runserver
```

Open <http://127.0.0.1:8000/> and sign in with the demo credentials above.

> On Windows, if `Activate.ps1` is blocked, run
> `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first, or just call
> the interpreter directly: `venv\Scripts\python.exe manage.py runserver`.

---

## Connecting to Neon PostgreSQL

1. Create a project at <https://neon.tech> and copy the **connection string** for
   your database (Neon's dashboard → *Connection Details*). It looks like:

   ```
   postgresql://USER:PASSWORD@ep-xxxx-pooler.region.aws.neon.tech/neondb?sslmode=require
   ```

2. Put it in `.env` as `DATABASE_URL` (already wired up if you used the provided
   `.env`):

   ```
   DATABASE_URL=postgresql://USER:PASSWORD@ep-xxxx-pooler.region.aws.neon.tech/neondb?sslmode=require
   ```

3. Run `python manage.py migrate`. That's it — `dj-database-url` parses the URL and
   `psycopg` connects over SSL.

> **Pooled vs direct:** the `-pooler` host (PgBouncer) is great for the web app.
> The Django **test runner** creates/drops databases and uses nested transactions,
> which a transaction-pooled connection doesn't love — so the test suite points at
> a throwaway SQLite database instead (see [Running the tests](#running-the-tests)).

---

## The premium engine in 30 seconds

Every policy has a `base_premium` and a `no_claim_streak`. The **No-Claim-Bonus**
discount is tiered by streak and capped at 25%:

| Claim-free periods | Discount |
| ------------------ | -------- |
| 1                  | 5%       |
| 2                  | 10%      |
| 3                  | 15%      |
| 4                  | 20%      |
| 5 or more          | 25% (cap)|

To see it work without waiting a year, open any policy and click **Run Renewal**
(or run `python manage.py run_renewal --policy POL-...`). The engine looks at the
renewal period just ending:

- **No approved/settled claims** → streak `+1`, next discount tier applied.
- **An approved or settled claim occurred** → streak resets to `0`, premium returns
  to base. (Merely *submitted* or *rejected* claims do **not** break the streak.)

Either way it advances the renewal date by a year and writes a `PremiumHistory`
audit row. Full design notes are in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Management commands

| Command | What it does |
| ------- | ------------ |
| `python manage.py seed_demo` | Wipe domain tables and seed the demo user + ~15 policyholders, ~20 policies (every NCB tier), ~25 claims. Deterministic and re-runnable. |
| `python manage.py reset_demo` | Truncate all domain tables and re-seed. Intended for the nightly cron. |
| `python manage.py run_renewal --policy POL-2026-00001` | Run a renewal for one policy. |
| `python manage.py run_renewal --all` | Run a renewal for every policy. |

---

## Deploying to Render

This repo includes a [`render.yaml`](render.yaml) blueprint and a
[`build.sh`](build.sh) build script.

1. Push the repo to GitHub.
2. In Render: **New + → Blueprint**, point it at your repo. Render reads
   `render.yaml` and provisions the web service.
3. Set the environment variables that are marked `sync: false` (they're not in the
   blueprint for safety):
   - `DATABASE_URL` — your Neon connection string.
   - `ALLOWED_HOSTS` — your Render hostname, e.g. `aegis-insurance.onrender.com`.
   - `SECRET_KEY` is auto-generated by the blueprint; `DEBUG` is set to `False`.
4. Deploy. The build runs `build.sh`:

   ```bash
   pip install -r requirements.txt
   python manage.py collectstatic --no-input
   python manage.py migrate --noinput
   python manage.py seed_demo
   ```

5. The app starts with `gunicorn config.wsgi`. WhiteNoise serves static files, so
   no CDN or separate static host is needed.

**Railway / Heroku-style platforms** work too: the [`Procfile`](Procfile) defines a
`web` process (`gunicorn config.wsgi`) and a `release` phase that runs migrations.
Set the same environment variables in the platform dashboard.

`RENDER_EXTERNAL_HOSTNAME` is trusted automatically when present, and HTTPS-related
hardening (HSTS, secure cookies, SSL redirect) switches on whenever `DEBUG=False`.

---

## Scheduling the nightly reset

Because this is a public demo, `reset_demo` restores a clean, populated database
every night. Two options:

**Option A — Render Cron Job** (defined in `render.yaml`; requires a paid instance):

```yaml
- type: cron
  name: aegis-nightly-reset
  schedule: "30 18 * * *"   # 00:00 IST (18:30 UTC)
  startCommand: "python manage.py reset_demo"
```

**Option B — GitHub Actions** (free; defined in
`.github/workflows/nightly-reset.yml`):

Add a repository **secret** named `DATABASE_URL` (your Neon string). The workflow
runs `python manage.py reset_demo` on a daily schedule and can also be triggered
manually from the *Actions* tab. Adjust the `cron:` line to change the time.

Any scheduler that can run a shell command works — the only requirement is access
to `DATABASE_URL`.

---

## Environment variables

| Variable | Required | Default | Purpose |
| -------- | -------- | ------- | ------- |
| `DATABASE_URL` | Yes (prod) | sqlite fallback | PostgreSQL/Neon connection string. |
| `SECRET_KEY` | Yes (prod) | insecure dev key | Django secret key. |
| `DEBUG` | No | `False` | Enable debug mode locally. |
| `ALLOWED_HOSTS` | Yes (prod) | `localhost,127.0.0.1` | Comma-separated hostnames. |
| `CSRF_TRUSTED_ORIGINS` | No | derived from hosts | Extra `https://` origins for CSRF. |
| `DEMO_ROW_LIMIT` | No | `200` | Max rows per domain table before writes are refused. |
| `DEMO_WRITE_RATE` | No | `30/m` | Per-IP POST budget (django-ratelimit syntax). |
| `DEMO_USERNAME` / `DEMO_PASSWORD` | No | `demo` / `demo1234` | Seeded demo credentials. |
| `DEMO_BANNER_TEXT` | No | "Demo environment — data resets daily." | Site-wide banner copy. |
| `TIME_ZONE` | No | `Asia/Kolkata` | Display time zone. |

See [`.env.example`](.env.example) for a ready-to-copy template.

---

## Running the tests

The suite covers the premium tiers, the renewal logic (increment, reset,
non-breaking claims, the 25% cap), input validation, and the demo row cap.

```bash
# Use a throwaway SQLite DB for tests (recommended; avoids pooled-connection quirks)
# macOS / Linux:
DATABASE_URL= python manage.py test
# Windows (PowerShell):
$env:DATABASE_URL=""; python manage.py test
```

---

## Project structure

```
aegis-insurance/
├── config/                 # Django project (settings, urls, wsgi)
├── insurance/              # The app
│   ├── models.py           # Policyholder, Policy, Claim, PremiumHistory
│   ├── services.py         # Premium engine + demo-safety helpers
│   ├── views.py            # Dashboard + CRUD + write_guard (rate limit)
│   ├── forms.py            # Validation (negative premiums, claim > sum insured…)
│   ├── admin.py            # Admin with the Run-Renewal action
│   ├── context_processors.py
│   ├── templatetags/       # ₹ Indian formatting + status badges
│   └── management/commands # seed_demo, reset_demo, run_renewal
├── templates/              # base + login + insurance/*
├── static/css/styles.css   # Hand-rolled medical-teal theme
├── requirements.txt
├── Procfile · runtime.txt · build.sh · render.yaml
├── .env.example
└── ARCHITECTURE.md
```

For the reasoning behind the premium engine and the demo-safety design, read
[ARCHITECTURE.md](ARCHITECTURE.md).
