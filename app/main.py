from fastapi import FastAPI
from app.db import run_migrations

app = FastAPI(title="Usage Metering & Billing Engine")


@app.on_event("startup")
def startup():
    run_migrations()


@app.get("/health")
def health():
    return {"status": "ok"}
