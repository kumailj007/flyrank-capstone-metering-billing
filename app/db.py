import os
import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ["DATABASE_URL"]


def get_conn():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def run_migrations():
    with get_conn() as conn:
        with open("migrations/001_init.sql") as f:
            conn.execute(f.read())
