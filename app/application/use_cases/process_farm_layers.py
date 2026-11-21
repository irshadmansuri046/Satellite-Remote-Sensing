import uuid
from typing import Any, Dict, Optional
from shapely.geometry import shape

from app.domain.entities.farm import Farm
from app.domain.entities.job import ProcessingJob, JobStatus
from app.domain.interfaces import FarmRepository, JobRepository

class ProcessFarmLayersUseCase:
    def __init__(self, farm_repo: FarmRepository, job_repo: JobRepository):
        self.farm_repo = farm_repo
        self.job_repo = job_repo

    async def execute(self, polygon: Dict[str, Any], farm_id_override: Optional[str] = None) -> ProcessingJob:
        # 1. Validate GeoJSON polygon using shapely
        try:
            geom = shape(polygon)
            if geom.geom_type != "Polygon":
                raise ValueError(f"Geometry must be a Polygon, got {geom.geom_type}")
            if not geom.is_valid:
                # Attempt to repair self-intersecting geometries
                geom = geom.buffer(0)
                if not geom.is_valid or geom.is_empty:
                    raise ValueError("Polygon geometry is invalid and could not be repaired.")
                from shapely.geometry import mapping
                polygon = mapping(geom)
        except Exception as e:
            raise ValueError(f"Invalid polygon GeoJSON structure: {e}")

        # 2. Setup Farm details
        farm_id = farm_id_override or f"farm_{uuid.uuid4().hex[:8]}"
        farm = Farm(
            id=farm_id,
            name=f"Farm {farm_id}",
            geometry=polygon
        )
        await self.farm_repo.save(farm)

        # 3. Create background processing job
        job_id = str(uuid.uuid4())
        job = ProcessingJob(
            id=job_id,
            farm_id=farm_id,
            status=JobStatus.PENDING
        )
        await self.job_repo.save(job)

        # 4. Dispatch background Celery task
        # Note: We import task here or pass task dispatcher to avoid circular imports.
        # We'll trigger Celery task directly using its signature name
        from app.infrastructure.queue.celery_app import celery_app
        celery_app.send_task(
            "app.workers.tasks.process_farm_raster_task",
            args=[job_id, farm_id, polygon],
            queue="celery"
        )

        return job
