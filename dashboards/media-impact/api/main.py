# backend/main.py - LLYC Intelligence Dashboard FastAPI Backend (GCP Cloud Run Deploy)
import os
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLYC Intelligence Dashboard API")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import and include routers
from app.services.mcp_analytics.endpoints import router as mcp_router

app.include_router(mcp_router, prefix="/api/v1/mcp-analytics", tags=["MCP Analytics"])
app.include_router(mcp_router, prefix="/media-impact/api/v1/mcp-analytics", tags=["MCP Analytics"])

# Setup static files directory path
STATIC_DIR = os.path.join(os.path.dirname(__file__), "app", "static", "media-impact")

# Serve assets folder statically
assets_dir = os.path.join(STATIC_DIR, "assets")
if os.path.exists(assets_dir):
    app.mount("/media-impact/assets", StaticFiles(directory=assets_dir), name="media_impact_assets")
    logger.info(f"Mounted static assets from: {assets_dir}")

@app.get("/media-impact/{path:path}")
async def serve_media_impact_catchall(request: Request, path: str):
    # Si la ruta apunta a un archivo estático físico (ej: favicon.svg, logo_llyc.svg, assets/...)
    file_path = os.path.join(STATIC_DIR, path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)

    # Si es una petición de API fallida, no servir el HTML de la SPA para evitar errores de tipo MIME
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")

    # Para cualquier otra ruta o subpath de cliente (ej: /media-impact/, /media-impact/sanitas), servir la index.html de la SPA
    spa_html = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(spa_html):
        return FileResponse(spa_html)
    
    raise HTTPException(status_code=404, detail="Media Impact Dashboard SPA index.html not found")

@app.get("/")
async def root():
    return {"message": "LLYC Intelligence Dashboard API is running", "status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

