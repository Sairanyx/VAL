from fastapi import FastAPI

from app.config import settings

app = FastAPI(title="Since AI Hackathon")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "env": settings.env}
