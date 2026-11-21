from typing import Any, Dict, Optional
from app.domain.entities.job import ProcessingJob
from app.domain.interfaces import JobRepository, RasterRepository, StorageService

class GetJobStatusUseCase:
    def __init__(self, job_repo: JobRepository):
        self.job_repo = job_repo

    async def execute(self, job_id: str) -> Optional[ProcessingJob]:
        return await self.job_repo.get_by_id(job_id)


class GetFarmLayersUseCase:
    def __init__(self, raster_repo: RasterRepository, storage_service: StorageService):
        self.raster_repo = raster_repo
        self.storage_service = storage_service

    async def execute(self, farm_id: str) -> Dict[str, Any]:
        """
        Retrieves processed layers for a farm, generating signed URLs for each.
        Returns a dict containing layers grouped by type and basic metadata.
        """
        layers = await self.raster_repo.get_layers_by_farm(farm_id)
        if not layers:
            return {}

        # Group layers by capture_date to ensure we get the latest processed run
        # Since layers are returned sorted by capture_date desc, the first capture_date is the latest
        latest_date = layers[0].capture_date
        latest_layers = [l for l in layers if l.capture_date == latest_date]

        layer_urls = {}
        for layer in latest_layers:
            signed_url = await self.storage_service.generate_presigned_url(layer.s3_path)
            layer_urls[layer.layer_type.value] = signed_url

        metadata = {
            "satellite": latest_layers[0].satellite,
            "captureDate": latest_layers[0].capture_date.strftime("%Y-%m-%d"),
            "cloudCover": latest_layers[0].cloud_cover
        }

        return {
            "farmId": farm_id,
            "layers": layer_urls,
            "metadata": metadata
        }


class GetFarmStatisticsUseCase:
    def __init__(self, raster_repo: RasterRepository):
        self.raster_repo = raster_repo

    async def execute(self, farm_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves the latest calculated index statistics for the farm.
        """
        return await self.raster_repo.get_latest_statistics(farm_id)
