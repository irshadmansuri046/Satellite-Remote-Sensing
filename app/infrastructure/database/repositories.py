import uuid
from typing import Any, Dict, List, Optional
from datetime import date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.domain.entities.farm import Farm
from app.domain.entities.job import ProcessingJob, JobStatus
from app.domain.entities.layer import RasterLayer, LayerType
from app.domain.interfaces import FarmRepository, JobRepository, RasterRepository
from app.infrastructure.database.models import (
    FarmModel,
    ProcessingJobModel,
    RasterLayerModel,
    LayerStatisticsModel,
)
from app.infrastructure.database.geo_utils import geojson_to_geometry, geometry_to_geojson

class SqlFarmRepository(FarmRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, farm: Farm) -> Farm:
        model = FarmModel(
            id=farm.id,
            name=farm.name,
            geometry=geojson_to_geometry(farm.geometry),
            created_at=farm.created_at,
        )
        await self.session.merge(model)
        await self.session.flush()
        return farm

    async def get_by_id(self, farm_id: str) -> Optional[Farm]:
        result = await self.session.execute(
            select(FarmModel).where(FarmModel.id == farm_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            return None
        return Farm(
            id=model.id,
            name=model.name,
            geometry=geometry_to_geojson(model.geometry),
            created_at=model.created_at,
        )


class SqlJobRepository(JobRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, job: ProcessingJob) -> ProcessingJob:
        model = ProcessingJobModel(
            id=job.id,
            farm_id=job.farm_id,
            status=job.status.value,
            error_message=job.error_message,
            created_at=job.created_at,
            updated_at=job.updated_at,
        )
        await self.session.merge(model)
        await self.session.flush()
        return job

    async def get_by_id(self, job_id: str) -> Optional[ProcessingJob]:
        result = await self.session.execute(
            select(ProcessingJobModel).where(ProcessingJobModel.id == job_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            return None
        return ProcessingJob(
            id=model.id,
            farm_id=model.farm_id,
            status=JobStatus(model.status),
            error_message=model.error_message,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

    async def update_status(
        self, job_id: str, status: JobStatus, error_message: Optional[str] = None
    ) -> ProcessingJob:
        result = await self.session.execute(
            select(ProcessingJobModel).where(ProcessingJobModel.id == job_id)
        )
        model = result.scalar_one_or_none()
        if not model:
            raise ValueError(f"Job with id {job_id} not found")
        model.status = status.value
        model.error_message = error_message
        await self.session.flush()
        return ProcessingJob(
            id=model.id,
            farm_id=model.farm_id,
            status=JobStatus(model.status),
            error_message=model.error_message,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


class SqlRasterRepository(RasterRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_layer(self, layer: RasterLayer) -> RasterLayer:
        model = RasterLayerModel(
            id=layer.id,
            farm_id=layer.farm_id,
            layer_type=layer.layer_type.value,
            s3_path=layer.s3_path,
            avg_value=layer.avg_value,
            capture_date=layer.capture_date,
            satellite=layer.satellite,
            cloud_cover=layer.cloud_cover,
            created_at=layer.created_at,
        )
        await self.session.merge(model)
        await self.session.flush()
        return layer

    async def get_layers_by_farm(self, farm_id: str) -> List[RasterLayer]:
        result = await self.session.execute(
            select(RasterLayerModel)
            .where(RasterLayerModel.farm_id == farm_id)
            .order_by(RasterLayerModel.capture_date.desc())
        )
        models = result.scalars().all()
        return [
            RasterLayer(
                id=m.id,
                farm_id=m.farm_id,
                layer_type=LayerType(m.layer_type),
                s3_path=m.s3_path,
                avg_value=m.avg_value,
                capture_date=m.capture_date,
                satellite=m.satellite,
                cloud_cover=m.cloud_cover,
                created_at=m.created_at,
            )
            for m in models
        ]

    async def get_latest_statistics(self, farm_id: str) -> Optional[Dict[str, Any]]:
        result = await self.session.execute(
            select(LayerStatisticsModel)
            .where(LayerStatisticsModel.farm_id == farm_id)
            .order_by(LayerStatisticsModel.capture_date.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        if not model:
            return None
        return {
            "avgNdvi": model.avg_ndvi,
            "vegetationCover": model.vegetation_cover,
            "leafNitrogen": model.leaf_nitrogen,
        }

    async def save_statistics(
        self, farm_id: str, capture_date: date, avg_ndvi: float, vegetation_cover: float, leaf_nitrogen: float
    ) -> None:
        result = await self.session.execute(
            select(LayerStatisticsModel)
            .where(LayerStatisticsModel.farm_id == farm_id)
            .where(LayerStatisticsModel.capture_date == capture_date)
        )
        model = result.scalar_one_or_none()
        if model:
            model.avg_ndvi = avg_ndvi
            model.vegetation_cover = vegetation_cover
            model.leaf_nitrogen = leaf_nitrogen
        else:
            model = LayerStatisticsModel(
                id=str(uuid.uuid4()),
                farm_id=farm_id,
                capture_date=capture_date,
                avg_ndvi=avg_ndvi,
                vegetation_cover=vegetation_cover,
                leaf_nitrogen=leaf_nitrogen,
            )
            self.session.add(model)
        await self.session.flush()
