# Architecture

This document explains the two parts of Aegis that carry the most design intent:
the **dynamic premium engine** and the **demo-safety layer** that lets the app be
deployed to the public internet without falling over.

---

## 1. Domain model

Four tables, one app (`insurance`):

```
Policyholder 1───* Policy 1───* Claim
                     │
                     └──* PremiumHistory   (append-only audit)
```

- **Policyholder** — the insured customer (name, email, DOB, gender, phone, …).
- **Policy** — a health policy. Carries the figures the engine works on:
  `base_premium`, `current_premium`, `no_claim_streak`, `sum_insured`,
  `start_date`, `renewal_date`, and `status` (Active/Lapsed).
- **Claim** — a claim against a policy, with a `status`
  (Submitted/Approved/Rejected/Settled) and a `claim_type`.
- **PremiumHistory** — one row per premium recalculation: the old premium, the new
  premium, the discount applied, the effective date, and a human-readable reason.
  Never updated or deleted — it's the audit trail.

`policy_number` and `claim_number` are auto-generated from the primary key on first
save (`POL-2026-00001`, `CLM-2026-00001`) so they're readable and stable.

### Why a service layer?

All premium logic lives in `insurance/services.py`, **not** in models or views. The
reason is that the same operation is triggered from three places — the dashboard
button, the Django admin action, and a management command. A single
`run_renewal(policy)` function means there is exactly one code path to reason about
and test, and no chance of the admin and the UI drifting apart.

---

## 2. The dynamic premium engine

### No-Claim-Bonus tiers

The discount is a pure function of the claim-free streak, capped at 25%:

```python
discount = min(5 * streak, 25)   # percent
```

| streak | 0 | 1 | 2 | 3 | 4 | 5 | 6+ |
| ------ | - | - | -- | -- | -- | -- | -- |
| %      | 0 | 5 | 10 | 15 | 20 | 25 | 25 |

This lives in `discount_for_streak()`; `premium_for(base, streak)` applies it and
rounds to paise with `ROUND_HALF_UP`. Both are tiny, side-effect-free, and
exhaustively unit-tested — the kind of money math you never want to guess about.

### `recalculate_premium(policy, reason, effective_date)`

The single mutation point for a premium. It:

1. reads the current streak,
2. computes the new premium from the base premium,
3. writes it onto the policy, and
4. **always** appends a `PremiumHistory` row.

"Every recalculation writes a history row" is a hard rule — the audit trail is only
trustworthy if there are no silent writes.

### `run_renewal(policy)` — simulating a year passing

A real NCB only updates once a year, which is useless for a demo. `run_renewal`
compresses that into a button press. Wrapped in a single transaction, it:

1. Defines the period being closed as the 12 months ending on the policy's current
   `renewal_date`.
2. Counts **approved or settled** claims with a `date_of_service` inside that
   window.
   - **Zero** → `no_claim_streak += 1` (move up a tier).
   - **One or more** → `no_claim_streak = 0` (premium returns to base).
3. Advances `renewal_date` by one year (with a Feb-29 → Feb-28 guard).
4. Calls `recalculate_premium(...)` with a descriptive reason.

**A deliberate modelling choice:** only *Approved* and *Settled* claims break the
streak. *Submitted* claims (not yet adjudicated) and *Rejected* claims (not the
insurer's payout) leave the bonus intact. That set is named once as
`CLAIM_AGAINST_STREAK` in `models.py` and reused by both the engine and the seed
data, so the rule can't be defined two different ways.

### Where it's invoked

| Trigger | Code |
| ------- | ---- |
| Dashboard "Run Renewal" button | `policy_run_renewal` view → `run_renewal()` |
| Admin bulk action | `run_renewal_action` → `run_renewal()` |
| CLI | `run_renewal` management command → `run_renewal()` |

---

## 3. Demo-safety design

The app is meant to be deployed publicly with the admin and write forms exposed.
Four layers keep that safe and cheap to run.

### a) Nightly reset (`reset_demo`)

A management command truncates every domain table and re-seeds. On PostgreSQL it
uses `TRUNCATE ... RESTART IDENTITY CASCADE`, so primary keys — and therefore the
generated policy/claim numbers — start clean again each night. It's scheduled by a
Render Cron Job or a free GitHub Actions workflow (see the README). The seed itself
is deterministic (`random.Random(42)`), so the demo always looks the same after a
reset.

### b) Row cap (`DEMO_ROW_LIMIT`, default 200)

Before any UI-driven create, `check_demo_limit(model)` compares the table's row
count to the cap and raises `DemoLimitReached` if it's full. The view turns that
into a friendly *"demo limit reached — resets nightly"* message and disables the
form's submit button. The cap is enforced in the **view/form layer, not the model**,
so the seed and reset commands (which legitimately create the baseline ~60 rows) are
never blocked.

### c) Per-IP write rate limiting

Every write view is wrapped by `write_guard`, a decorator that composes
`login_required` with `django-ratelimit` (`key="ip"`, `method="POST"`, rate from
`DEMO_WRITE_RATE`, default `30/m`). It runs in non-blocking mode: when the limit is
hit, the request isn't hard-rejected with a raw 403 — instead the view redirects
back with a polite *"you're doing that too fast"* message. Counters live in
`LocMemCache`, which needs no extra infrastructure.

### d) Input validation

Model field validators reject negatives at the database boundary, and the forms add
the cross-field and sanity checks that make the demo robust:

- claim amount may not exceed the policy's sum insured,
- premiums and sums insured must be positive and within realistic bounds,
- dates of birth / service can't be in the future,
- renewal date must follow the start date.

---

## 4. Configuration & deployment posture

- **Everything is environment-driven** (`config/settings.py` reads `os.environ`,
  with `python-dotenv` loading `.env` locally). The same image runs in dev and prod.
- **`DATABASE_URL`** is parsed by `dj-database-url`; if it's absent, settings fall
  back to SQLite so commands like `collectstatic` and the test suite work anywhere.
- **WhiteNoise** serves compressed, hashed static files directly from the web
  process — no CDN, no separate static host.
- **Security hardening** (HSTS, secure cookies, SSL redirect, proxy SSL header)
  activates automatically when `DEBUG=False`, and `RENDER_EXTERNAL_HOSTNAME` is
  trusted when present.

The guiding principle throughout: keep the moving parts in one place, make the money
math boring and tested, and assume the internet will poke at every form.
