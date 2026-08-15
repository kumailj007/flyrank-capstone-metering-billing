import glob
import os

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def run_migrations():
    """Run every migration file in order. Each file is written to be
    re-runnable (IF NOT EXISTS / ADD COLUMN IF NOT EXISTS)."""
    with get_conn() as conn:
        for path in sorted(glob.glob("migrations/*.sql")):
            with open(path) as f:
                conn.execute(f.read())
