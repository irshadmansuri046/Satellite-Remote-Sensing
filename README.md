# Agricultural Remote Sensing Farm Analytics Platform

Production-ready agricultural remote sensing backend built with Python 3.12, FastAPI, Celery, PostgreSQL/PostGIS, Rasterio, and Cloudflare R2. The system receives a farm boundary polygon, retrieves Sentinel-2 L2A satellite data, clips it to the farm boundaries, and generates three cloud-optimized GeoTIFF (COG) layers: **NDVI**, **Vegetation Cover (FVC)**, and **Leaf Nitrogen**.

---

## 🏗️ Architecture Design (Hexagonal / Ports & Adapters)

This backend implements a clean **Hexagonal Architecture** that decouples our core agronomic domain logic from databases, messaging brokers, cloud storage APIs, and satellite servers:

- **Domain Layer (`app/domain`)**: Contains pure dataclasses and business rules (e.g., NDVI boundaries, Job Enums) and repository/service interfaces (Ports). Strictly framework-agnostic.
- **Application Layer (`app/application`)**: Coordinates use cases (Commands and Queries), validating parameters and orchestrating adapter calls.
- **Infrastructure Layer (`app/infrastructure`)**: Implements external ports (Adapters) using concrete technologies (SQLAlchemy/PostGIS database repositories, STAC planetary query engines, boto3 Cloudflare R2 storage drivers).
- **API Layer (`app/api`)**: Delivery mechanism exposing REST controllers, request routing, validation, and serialization.
- **Worker Layer (`app/workers`)**: Background Celery task processing pipelines, listening on Redis.

```
                  ┌───────────────────────────────┐
                  │           API Layer           │
                  │      (endpoints, routes)      │
                  └───────────────┬───────────────┘
                                  │ (triggers)
                  ┌───────────────▼───────────────┐
                  │       Application Layer       │
                  │     (Use Cases, Commands)     │
                  └───────────────┬───────────────┘
                                  │ (interfaces / ports)
  ┌───────────────────────────────┼───────────────────────────────┐
  │ Infrastructure Layer          │          Domain Layer         │
  │ (SQLAlchemy, PostGIS, Celery) │  (Farm, RasterLayer, Job)     │
  └───────────────────────────────┴───────────────────────────────┘
```

---

## 🗄️ Database Schema Design

The platform uses a relational **PostgreSQL + PostGIS** schema to support high-performance spatial geoqueries:

1. **`farms`**: Stores farm properties. Holds a spatial geometry column `geometry` mapping the farm polygon (SRID 4326) with a spatial GIST index.
2. **`processing_jobs`**: Tracks async task statuses (`PENDING`, `RUNNING`, `COMPLETED`, `FAILED`) and execution stack traces.
3. **`satellite_scenes`**: Caches Sentinel-2 metadata (scene ID, cloud cover, acquisition date, footprint polygon).
4. **`raster_layers`**: Stores references to generated COG assets (`ndvi`, `vegetation`, `leafNitrogen`), their R2 storage paths, and average index values.
5. **`layer_statistics`**: Records historical, aggregated farm index performance.
6. **`audit_logs`**: Logs changes and analytics execution tracking.

---

## 🚀 Local Development Setup

### Prerequisites
- Docker & Docker Compose
- Python 3.12+ (if running tests or server locally without containers)
- GDAL and PROJ command line tools (installed automatically in Docker container)

### Step 1: Clone and Build Containers
Run the multi-container configuration:
```bash
docker compose up --build
```
This spawns:
- **`db`**: PostGIS database on port `5432`
- **`redis`**: Broker/backend on port `6379`
- **`api`**: FastAPI server on port `8000` (auto-bootstraps DB tables and extensions on startup)
- **`worker`**: Celery worker listening on tasks

### Step 2: Triggering a Job (API Verification)
Submit a farm polygon GeoJSON to `/api/v1/layers` using `curl` or FastAPI Swagger GUI (`http://localhost:8000/docs`):

```bash
curl -X POST "http://localhost:8000/api/v1/layers" \
     -H "Content-Type: application/json" \
     -d '{
       "polygon": {
         "type": "Polygon",
         "coordinates": [
           [
             [19.871879647, 72.869778873],
             [19.872241995, 72.871039922],
             [19.872782464, 72.872922576],
             [19.873066589, 72.874827299],
             [19.871912539, 72.875366562],
             [19.870378323, 72.874504813],
             [19.871921891, 72.869923324],
             [19.871879647, 72.869778873]
           ]
         ]
       }
     }'
```

Response:
```json
{
  "jobId": "da3b6d26-72aa-49cc-8df3-5755106511bf",
  "farmId": "farm_83bcda87",
  "status": "PENDING"
}
```

### Step 3: Check Processing Progress
Check task execution details using `/api/v1/jobs/{jobId}`:
```bash
curl http://localhost:8000/api/v1/jobs/da3b6d26-72aa-49cc-8df3-5755106511bf
```

### Step 4: Fetch Layer URLs and Statistics
Once the job transitions to `COMPLETED`, fetch the pre-signed URLs (or local routes in fallback mode) and computed averages:

```bash
# Retrieve raster layers (NDVI, Vegetation Cover, Leaf Nitrogen)
curl http://localhost:8000/api/v1/layers/farm_83bcda87

# Retrieve average index statistics
curl http://localhost:8000/api/v1/statistics/farm_83bcda87
```

---

## 🧪 Testing Suite

Tests utilize mock repository dependencies and synthetic numpy raster structures. This lets you run the test suite instantly without a running database or active network connections.

### Setup and Execution:
```bash
# Setup virtual environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install greenlet

# Run tests with coverage report
PYTHONPATH=. pytest --cov=app tests/
```

---

## ☁️ Production Deployment (Railway & R2)

### Cloudflare R2 Configuration
Add these environment variables to connect your Cloudflare R2 bucket:
- `R2_ENDPOINT_URL`: `https://<account-id>.r2.cloudflarestorage.com`
- `R2_ACCESS_KEY_ID`: Cloudflare API Access Key
- `R2_SECRET_ACCESS_KEY`: Cloudflare API Secret Key
- `R2_BUCKET_NAME`: `farm-rasters`
- `R2_PUBLIC_URL_PREFIX`: (Optional) Custom domain linked to the bucket (e.g. `https://rasters.myfarm.com`)

### Deploying to Railway
1. **Database Service**: Add a **PostgreSQL** service in Railway and enable **PostGIS** (our lifespan bootstrapper runs `CREATE EXTENSION IF NOT EXISTS postgis;` automatically).
2. **Queue Service**: Add a **Redis** service in Railway.
3. **API Service**: Add a service pointing to your GitHub repository. Set the start command to:
   `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. **Worker Service**: Add another service pointing to the same repository. Set the start command to:
   `celery -A app.infrastructure.queue.celery_app worker --loglevel=info`
5. **Config variables**: In the API and Worker service settings, map:
   - `DATABASE_URL` (using Railway's PG connection URL)
   - `REDIS_URL` (using Railway's Redis connection URL)
   - `SATELLITE_MOCK` = `false` (to run real Sentinel-2 STAC downloads)
   - Add R2 credentials.
