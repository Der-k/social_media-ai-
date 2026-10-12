"""FastAPI entry point.  Run:  uvicorn app.main:app --reload"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.data.storage import get_store
from app.web.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_store().read()  # creates instance/demo_state.json on first run
    yield


app = FastAPI(title="Compass - social media analytics demo", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
app.include_router(router)
