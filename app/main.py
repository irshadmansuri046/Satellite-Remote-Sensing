import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.api.endpoints import router as api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-bootstrap database tables and spatial indexing on startup
    from app.infrastructure.database.session import create_tables_if_not_exists
    import anyio
    
    logger = anyio.to_thread.current_default_thread_limiter
    try:
        # Run sync table creation in worker threadpool to avoid blocking FastAPI startup
        await anyio.to_thread.run_sync(create_tables_if_not_exists)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to auto-create tables: {e}")
        
    yield
    # Cleanup tasks on shutdown (if any) go here

app = FastAPI(
    title=settings.APP_NAME,
    description="Production-grade agricultural remote sensing platform processing farm polygons and returning NDVI, Vegetation Cover, and Leaf Nitrogen layers.",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for cross-origin frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API Router
app.include_router(api_router, prefix=settings.API_V1_STR)

# Mount local storage folder as static endpoint fallback for local downloads
processed_dir = os.path.join(settings.TEMP_DIR, "processed")
os.makedirs(processed_dir, exist_ok=True)
app.mount("/api/v1/static", StaticFiles(directory=processed_dir), name="static")

@app.get("/", tags=["Root"])
def root_redirect():
    return {
        "message": f"Welcome to {settings.APP_NAME} API",
        "docs": "/docs",
        "health": "/api/v1/health"
    }
