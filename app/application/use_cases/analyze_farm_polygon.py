import time
import uuid
import asyncio
from typing import Any, Dict, Optional
from shapely.geometry import shape, mapping

from app.domain.entities.farm import Farm
from app.domain.entities.job import ProcessingJob, JobStatus
from app.domain.interfaces import FarmRepository, JobRepository, RasterRepository, StorageService
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.database.repositories import SqlFarmRepository, SqlJobRepository, SqlRasterRepository
from app.infrastructure.storage.r2_storage import R2StorageService
from app.application.use_cases.get_farm_data import GetFarmLayersUseCase, GetFarmStatisticsUseCase
from app.infrastructure.queue.celery_app import celery_app

class AnalyzeFarmPolygonUseCase:
    def __init__(
        self,
        farm_repo: Optional[FarmRepository] = None,
        job_repo: Optional[JobRepository] = None,
        raster_repo: Optional[RasterRepository] = None,
        storage_service: Optional[StorageService] = None,
    ):
        self.farm_repo = farm_repo
        self.job_repo = job_repo
        self.raster_repo = raster_repo
        self.storage_service = storage_service

    async def _get_job_status(self, job_id: str) -> Optional[ProcessingJob]:
        if self.job_repo:
            return await self.job_repo.get_by_id(job_id)
        async with AsyncSessionLocal() as session:
            repo = SqlJobRepository(session)
            return await repo.get_by_id(job_id)

    async def _attach_results(self, response: Dict[str, Any], farm_id: str) -> None:
        if self.raster_repo and self.storage_service:
            layers_use_case = GetFarmLayersUseCase(self.raster_repo, self.storage_service)
            stats_use_case = GetFarmStatisticsUseCase(self.raster_repo)
            layers_data = await layers_use_case.execute(farm_id)
            stats_data = await stats_use_case.execute(farm_id)
        else:
            async with AsyncSessionLocal() as session:
                r_repo = SqlRasterRepository(session)
                s_service = R2StorageService()
                layers_use_case = GetFarmLayersUseCase(r_repo, s_service)
                stats_use_case = GetFarmStatisticsUseCase(r_repo)
                layers_data = await layers_use_case.execute(farm_id)
                stats_data = await stats_use_case.execute(farm_id)

        if layers_data:
            response["layers"] = layers_data.get("layers")
            response["metadata"] = layers_data.get("metadata")
        if stats_data:
            response["statistics"] = stats_data

    async def execute(
        self,
        polygon: Dict[str, Any],
        farm_id_override: Optional[str] = None,
        wait: bool = True,
        timeout_seconds: int = 120,
    ) -> Dict[str, Any]:
        # 1. Validate GeoJSON polygon using shapely
        try:
            geom = shape(polygon)
            if geom.geom_type != "Polygon":
                raise ValueError(f"Geometry must be a Polygon, got {geom.geom_type}")
            if not geom.is_valid:
                geom = geom.buffer(0)
                if not geom.is_valid or geom.is_empty:
                    raise ValueError("Polygon geometry is invalid and could not be repaired.")
                polygon = mapping(geom)
        except Exception as e:
            raise ValueError(f"Invalid polygon GeoJSON structure: {e}")

        farm_id = farm_id_override or f"farm_{uuid.uuid4().hex[:8]}"
        farm = Farm(id=farm_id, name=f"Farm {farm_id}", geometry=polygon)
        job_id = str(uuid.uuid4())
        job = ProcessingJob(id=job_id, farm_id=farm_id, status=JobStatus.PENDING)

        # 2. Persist farm and initial job
        if self.farm_repo and self.job_repo:
            await self.farm_repo.save(farm)
            await self.job_repo.save(job)
        else:
            async with AsyncSessionLocal() as session:
                f_repo = SqlFarmRepository(session)
                j_repo = SqlJobRepository(session)
                await f_repo.save(farm)
                await j_repo.save(job)
                await session.commit()

        # 3. Dispatch Celery background task
        celery_app.send_task(
            "app.workers.tasks.process_farm_raster_task",
            args=[job_id, farm_id, polygon],
            queue="celery",
        )

        response: Dict[str, Any] = {
            "jobId": job_id,
            "farmId": farm_id,
            "status": job.status.value,
            "errorMessage": None,
            "polygon": polygon,
            "layers": None,
            "metadata": None,
            "statistics": None,
            "relatedEndpoints": {
                "jobStatus": f"/api/v1/jobs/{job_id}",
                "layers": f"/api/v1/layers/{farm_id}",
                "statistics": f"/api/v1/statistics/{farm_id}",
                "analysis": "/api/v1/analysis",
            },
        }

        if not wait:
            return response

        # 4. Wait / poll until completed or timeout
        start_time = time.time()
        poll_interval = 1.0

        while time.time() - start_time < timeout_seconds:
            await asyncio.sleep(poll_interval)
            current_job = await self._get_job_status(job_id)
            if current_job:
                response["status"] = current_job.status.value
                response["errorMessage"] = current_job.error_message
                if current_job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                    break

        # 5. If completed, attach layers & stats
        if response["status"] == JobStatus.COMPLETED.value:
            await self._attach_results(response, farm_id)

        return response
