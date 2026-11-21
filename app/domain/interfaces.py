from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from datetime import date
from app.domain.entities.farm import Farm
from app.domain.entities.job import ProcessingJob, JobStatus
from app.domain.entities.layer import RasterLayer

class FarmRepository(ABC):
    @abstractmethod
    async def save(self, farm: Farm) -> Farm:
        pass

    @abstractmethod
    async def get_by_id(self, farm_id: str) -> Optional[Farm]:
        pass

class JobRepository(ABC):
    @abstractmethod
    async def save(self, job: ProcessingJob) -> ProcessingJob:
        pass

    @abstractmethod
    async def get_by_id(self, job_id: str) -> Optional[ProcessingJob]:
        pass

    @abstractmethod
    async def update_status(
        self, job_id: str, status: JobStatus, error_message: Optional[str] = None
    ) -> ProcessingJob:
        pass

class RasterRepository(ABC):
    @abstractmethod
    async def save_layer(self, layer: RasterLayer) -> RasterLayer:
        pass

    @abstractmethod
    async def get_layers_by_farm(self, farm_id: str) -> List[RasterLayer]:
        pass

    @abstractmethod
    async def get_latest_statistics(self, farm_id: str) -> Optional[Dict[str, Any]]:
        pass

    @abstractmethod
    async def save_statistics(
        self, farm_id: str, capture_date: date, avg_ndvi: float, vegetation_cover: float, leaf_nitrogen: float
    ) -> None:
        pass

class SatelliteService(ABC):
    @abstractmethod
    async def search_latest_scene(
        self, geometry: Dict[str, Any], max_cloud_cover: float = 20.0
    ) -> Dict[str, Any]:
        """
        Searches for the latest available Sentinel-2 scene covering the geometry.
        Returns scene metadata (ID, capture date, cloud cover, and band asset URLs).
        """
        pass

    @abstractmethod
    async def download_bands_window(
        self, scene_metadata: Dict[str, Any], geometry: Dict[str, Any], output_dir: str
    ) -> Dict[str, str]:
        """
        Using rasterio's windowed reading or client-side cropping, fetch only the
        required bounding box area for bands B04, B05, B08.
        Returns a dictionary mapping band name (e.g. 'B04', 'B05', 'B08') to local file paths.
        """
        pass

class StorageService(ABC):
    @abstractmethod
    async def upload_file(self, local_path: str, s3_key: str) -> str:
        """
        Uploads a file to cloud storage (e.g., Cloudflare R2).
        Returns the s3 uri or public URL path.
        """
        pass

    @abstractmethod
    async def generate_presigned_url(self, s3_key: str, expiration: int = 3600) -> str:
        """
        Generates a temporary pre-signed URL for client access.
        """
        pass
