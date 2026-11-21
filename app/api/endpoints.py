from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.infrastructure.database.session import get_async_db
from app.infrastructure.database.repositories import SqlFarmRepository, SqlJobRepository, SqlRasterRepository
from app.infrastructure.storage.r2_storage import R2StorageService
from app.application.use_cases.process_farm_layers import ProcessFarmLayersUseCase
from app.application.use_cases.get_farm_data import (
    GetJobStatusUseCase,
    GetFarmLayersUseCase,
    GetFarmStatisticsUseCase,
)
from app.application.use_cases.analyze_farm_polygon import AnalyzeFarmPolygonUseCase
from app.domain.entities.job import JobStatus

router = APIRouter()

# Input Validation Models
class PolygonGeometry(BaseModel):
    type: str = Field("Polygon", description="GeoJSON geometry type")
    coordinates: List[List[List[float]]] = Field(..., description="WGS84 lon,lat coordinate arrays")

class ProcessLayersRequest(BaseModel):
    polygon: PolygonGeometry


# Response Models
class JobInitiatedResponse(BaseModel):
    jobId: str
    farmId: str
    status: str

class JobStatusResponse(BaseModel):
    jobId: str
    farmId: str
    status: str
    errorMessage: Optional[str] = None

class LayerUrlsResponse(BaseModel):
    farmId: str
    layers: Dict[str, str]
    metadata: Dict[str, Any]

class StatisticsResponse(BaseModel):
    farmId: str
    statistics: Dict[str, Any]

class RelatedEndpoints(BaseModel):
    jobStatus: str
    layers: str
    statistics: str
    analysis: str

class FarmAnalysisResponse(BaseModel):
    jobId: str
    farmId: str
    status: str
    errorMessage: Optional[str] = None
    polygon: PolygonGeometry
    layers: Optional[Dict[str, str]] = None
    metadata: Optional[Dict[str, Any]] = None
    statistics: Optional[Dict[str, Any]] = None
    relatedEndpoints: RelatedEndpoints

# Dependency Helpers for DI
def get_farm_repo(db: AsyncSession = Depends(get_async_db)) -> SqlFarmRepository:
    return SqlFarmRepository(db)

def get_job_repo(db: AsyncSession = Depends(get_async_db)) -> SqlJobRepository:
    return SqlJobRepository(db)

def get_raster_repo(db: AsyncSession = Depends(get_async_db)) -> SqlRasterRepository:
    return SqlRasterRepository(db)

def get_storage_service() -> R2StorageService:
    return R2StorageService()


# Endpoints
@router.post(
    "/layers",
    response_model=JobInitiatedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Satellite Index Computations",
    description="Receives a GeoJSON polygon, creates a farm record, and dispatches a Celery worker task."
)
async def process_layers(
    request: ProcessLayersRequest,
    farmId: Optional[str] = Query(None, description="Optional custom farm identifier"),
    farm_repo: SqlFarmRepository = Depends(get_farm_repo),
    job_repo: SqlJobRepository = Depends(get_job_repo)
):
    use_case = ProcessFarmLayersUseCase(farm_repo, job_repo)
    try:
        # Convert Pydantic shape to dictionary geometry representation
        geom_dict = request.polygon.model_dump()
        job = await use_case.execute(geom_dict, farm_id_override=farmId)
        return JobInitiatedResponse(
            jobId=job.id,
            farmId=job.farm_id,
            status=job.status.value
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {e}"
        )


@router.post(
    "/analysis",
    response_model=FarmAnalysisResponse,
    summary="Analyze farm polygon and return full results",
    description=(
        "Accepts a GeoJSON polygon, triggers satellite processing, waits for completion "
        "(by default), and returns job status, layer URLs, metadata, and statistics in one response."
    ),
    responses={
        200: {"description": "Processing completed; full results returned"},
        202: {"description": "Processing still in progress after timeout; partial results returned"},
        422: {"description": "Processing failed"},
    },
)
async def analyze_farm_polygon(
    request: ProcessLayersRequest,
    farmId: Optional[str] = Query(None, description="Optional custom farm identifier"),
    wait: bool = Query(True, description="Wait for background processing to finish before responding"),
    timeoutSeconds: int = Query(120, ge=5, le=600, description="Max seconds to wait when wait=true"),
):
    use_case = AnalyzeFarmPolygonUseCase()
    try:
        geom_dict = request.polygon.model_dump()
        result = await use_case.execute(
            geom_dict,
            farm_id_override=farmId,
            wait=wait,
            timeout_seconds=timeoutSeconds,
        )

        response = FarmAnalysisResponse(**result)

        if result["status"] == JobStatus.FAILED.value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=response.model_dump(),
            )

        if wait and result["status"] != JobStatus.COMPLETED.value:
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=response.model_dump(),
            )

        return response

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An unexpected error occurred: {e}",
        )


@router.get(
    "/jobs/{id}",
    response_model=JobStatusResponse,
    summary="Query processing job status",
    description="Check the current status (PENDING, RUNNING, COMPLETED, FAILED) of a processing job."
)
async def get_job_status(
    id: str,
    job_repo: SqlJobRepository = Depends(get_job_repo)
):
    use_case = GetJobStatusUseCase(job_repo)
    job = await use_case.execute(id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job with id {id} not found"
        )
    return JobStatusResponse(
        jobId=job.id,
        farmId=job.farm_id,
        status=job.status.value,
        errorMessage=job.error_message
    )


@router.get(
    "/layers/{farmId}",
    response_model=LayerUrlsResponse,
    summary="Get layer signed URLs",
    description="Retrieves the latest processed Sentinel-2 layers (NDVI, Vegetation, Leaf Nitrogen) with pre-signed URLs."
)
async def get_farm_layers(
    farmId: str,
    raster_repo: SqlRasterRepository = Depends(get_raster_repo),
    storage_service: R2StorageService = Depends(get_storage_service)
):
    use_case = GetFarmLayersUseCase(raster_repo, storage_service)
    data = await use_case.execute(farmId)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No processed layers found for farm {farmId}"
        )
    return LayerUrlsResponse(**data)


@router.get(
    "/statistics/{farmId}",
    response_model=StatisticsResponse,
    summary="Get farm level average stats",
    description="Retrieves the latest farm average index metrics (avgNdvi, vegetationCover, leafNitrogen)."
)
async def get_farm_statistics(
    farmId: str,
    raster_repo: SqlRasterRepository = Depends(get_raster_repo)
):
    use_case = GetFarmStatisticsUseCase(raster_repo)
    stats = await use_case.execute(farmId)
    if not stats:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No statistics found for farm {farmId}"
        )
    return StatisticsResponse(farmId=farmId, statistics=stats)


@router.get(
    "/health",
    summary="Health check diagnostic",
    description="Pings PostgreSQL database and checks connectivity to Redis broker queue."
)
async def health_check(db: AsyncSession = Depends(get_async_db)):
    health_status = {"status": "healthy", "components": {}}
    
    # 1. Test database connection
    try:
        await db.execute(text("SELECT 1"))
        health_status["components"]["database"] = "up"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["components"]["database"] = f"down (Error: {e})"

    # 2. Test redis connection
    import redis
    from app.config import settings
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        r.ping()
        health_status["components"]["redis"] = "up"
    except Exception as e:
        health_status["status"] = "unhealthy"
        health_status["components"]["redis"] = f"down (Error: {e})"

    if health_status["status"] == "unhealthy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_status
        )

    return health_status
