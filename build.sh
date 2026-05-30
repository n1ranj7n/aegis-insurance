#!/usr/bin/env bash
# Render build command. Installs deps, collects static files, runs migrations.
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --noinput

# Seed once on first deploy if the database is empty (safe to leave on for a demo).
python manage.py seed_demo
