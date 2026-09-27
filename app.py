"""Hugging Face Space entry point for the Debug2Learn FastAPI backend."""

import os

import uvicorn

from server import app


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "7860")),
    )
