"""FastAPI application entry point for the Academic Paper Analyzer MVP."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.v1 import documents, reviews

app = FastAPI(
    title="Academic Paper Analyzer API",
    version="0.1.0",
    description="MVP backend for asynchronous academic paper review.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router, prefix="/api/v1")
app.include_router(reviews.router, prefix="/api/v1")
