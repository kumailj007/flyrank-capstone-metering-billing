"""Tiny scheduler loop for the reconciler — runs the job every
RECONCILE_INTERVAL_SECONDS (default 24h; set low in dev to watch it work).
In production this would be cron / Inngest / Celery beat; a loop keeps
the capstone's $0, no-extra-infra promise."""
import os
import time

from jobs.reconcile import main

INTERVAL = int(os.environ.get("RECONCILE_INTERVAL_SECONDS", "86400"))

if __name__ == "__main__":
    while True:
        main()
        time.sleep(INTERVAL)
