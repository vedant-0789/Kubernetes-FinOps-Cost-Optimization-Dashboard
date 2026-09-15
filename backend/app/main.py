from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging

from app.config import settings
from app.db.database import engine, Base, SessionLocal
from app.engine.mock_generator import MockDataGenerator
from app.engine.scheduler import start_scheduler, stop_scheduler

from app.routers import overview, namespaces, zombies, recommendations, actions, lifecycle, settings as settings_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup sequence
    logger.info("Initializing FinOps Database tables...")
    Base.metadata.create_all(bind=engine)
    
    # Seed mock data
    db = SessionLocal()
    try:
        MockDataGenerator.seed_initial_data(db)
    finally:
        db.close()
        
    # Start background scheduler
    start_scheduler()
    logger.info("Kubernetes FinOps Backend ready!")
    yield
    # Shutdown sequence
    stop_scheduler()

app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Kubernetes FinOps & Cost-Optimization API with OpenCost allocation, zombie detection, p95 right-sizing, and automated remediation.",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for React Frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include Routers
app.include_router(overview.router)
app.include_router(namespaces.router)
app.include_router(zombies.router)
app.include_router(recommendations.router)
app.include_router(actions.router)
app.include_router(lifecycle.router)
app.include_router(settings_router.router)

@app.get("/")
def root_status():
    return {
        "status": "online",
        "service": "Kubernetes FinOps Cost-Optimization Dashboard API",
        "mock_mode": settings.MOCK_MODE,
        "docs": "/docs"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
