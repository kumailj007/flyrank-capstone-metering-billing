"""Seed plans + two demo tenants. Idempotent -- safe to run twice."""
from app.db import get_conn, run_migrations

run_migrations()

with get_conn() as conn:
    conn.execute("""
        INSERT INTO plans (id, api_call_limit, ai_token_limit) VALUES
        ('free', 1000, 100000),
        ('pro', 100000, 10000000)
        ON CONFLICT (id) DO NOTHING
    """)
    for name in ("Acme Corp", "Globex"):
        row = conn.execute(
            "SELECT id FROM tenants WHERE name = %s", (name,)
        ).fetchone()
        if not row:
            row = conn.execute(
                "INSERT INTO tenants (name) VALUES (%s) RETURNING id", (name,)
            ).fetchone()
            conn.execute(
                "INSERT INTO subscriptions (tenant_id, plan_id) VALUES (%s, 'free')",
                (row["id"],),
            )
        print(f"{name}: {row['id']}")

print("Seed complete.")
