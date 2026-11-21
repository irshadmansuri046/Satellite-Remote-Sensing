import os
import shutil
import logging
import asyncio
import uuid
from datetime import datetime
from celery import shared_task

from app.config import settings
from app.domain.entities.job import JobStatus
from app.domain.entities.layer import RasterLayer, LayerType
from app.infrastructure.database.session import AsyncSessionLocal
from app.infrastructure.database.repositories import SqlJobRepository, SqlRasterRepository
from app.infrastructure.satellite.stac_satellite import StacSatelliteService
from app.infrastructure.storage.r2_storage import R2StorageService
from app.infrastructure.raster.raster_engine import RasterEngine

logger = logging.getLogger(__name__)

async def async_process_farm_raster(job_id: str, farm_id: str, polygon: dict) -> None:
    # Set up localized workspace for this job
    job_temp_dir = os.path.join(settings.TEMP_DIR, "jobs", job_id)
    os.makedirs(job_temp_dir, exist_ok=True)

    async with AsyncSessionLocal() as session:
        job_repo = SqlJobRepository(session)
        raster_repo = SqlRasterRepository(session)

        # 1. Update job to RUNNING
        await job_repo.update_status(job_id, JobStatus.RUNNING)
        await session.commit()

        try:
            # 2. Instantiate dependencies
            # If SATELLITE_MOCK env is enabled, service defaults to Mock mode
            mock_mode = os.getenv("SATELLITE_MOCK", "false").lower() == "true"
            satellite_service = StacSatelliteService(mock_mode=mock_mode)
            storage_service = R2StorageService()

            # 3. Search scene
            logger.info(f"Job {job_id}: Searching Sentinel-2 L2A scene...")
            scene = await satellite_service.search_latest_scene(polygon, max_cloud_cover=20.0)
            capture_date = scene["capture_date"]
            cloud_cover = scene["cloud_cover"]
            scene_id = scene["scene_id"]
            satellite = scene["satellite"]

            # 4. Download cropped band windows
            logger.info(f"Job {job_id}: Downloading crop window of bands for scene {scene_id}...")
            band_paths = await satellite_service.download_bands_window(scene, polygon, job_temp_dir)

            # 5. Compute indices & statistics
            logger.info(f"Job {job_id}: Processing indices NDVI, FVC, NDRE...")
            indices, stats, meta = RasterEngine.calculate_indices(band_paths, polygon)

            # 6. Export COGs & upload to storage
            for name, array in indices.items():
                local_cog_path = os.path.join(job_temp_dir, f"{name}_{scene_id}.tif")
                # Write local COG
                RasterEngine.export_cog(array, meta, local_cog_path)
                
                # Define cloud storage key path (e.g. processed/ndvi/farm_abc/scene_xyz.tif)
                s3_key = f"processed/{name}/{farm_id}/{scene_id}.tif"
                
                # Upload
                s3_path = await storage_service.upload_file(local_cog_path, s3_key)

                # Save layer database entry
                layer_entity = RasterLayer(
                    id=str(uuid.uuid4()),
                    farm_id=farm_id,
                    layer_type=LayerType(name),
                    s3_path=s3_key,  # Store the key; signed URL generator will append endpoint/auth dynamically
                    avg_value=stats["avgNdvi"] if name == "ndvi" else stats["vegetationCover"] if name == "vegetation" else stats["leafNitrogen"],
                    capture_date=capture_date,
                    satellite=satellite,
                    cloud_cover=cloud_cover
                )
                await raster_repo.save_layer(layer_entity)

            # 7. Save aggregate statistics
            await raster_repo.save_statistics(
                farm_id=farm_id,
                capture_date=capture_date,
                avg_ndvi=stats["avgNdvi"],
                vegetation_cover=stats["vegetationCover"],
                leaf_nitrogen=stats["leafNitrogen"]
            )

            # 8. Mark job as COMPLETED
            await job_repo.update_status(job_id, JobStatus.COMPLETED)
            await session.commit()
            logger.info(f"Job {job_id}: Successfully completed agricultural remote sensing pipeline.")

        except Exception as e:
            logger.exception(f"Job {job_id}: Failed during execution. Reason: {e}")
            # Update job status to FAILED
            await job_repo.update_status(job_id, JobStatus.FAILED, error_message=str(e))
            await session.commit()
            raise e

        finally:
            # 9. Clean up job working directory
            if os.path.exists(job_temp_dir):
                shutil.rmtree(job_temp_dir)
                logger.info(f"Job {job_id}: Cleaned up temporary directory.")


@shared_task(
    name="app.workers.tasks.process_farm_raster_task",
    bind=True,
    max_retries=3,
    default_retry_delay=15
)
def process_farm_raster_task(self, job_id: str, farm_id: str, polygon: dict) -> None:
    """
    Celery task wrapper running the asynchronous geospatial processing pipeline.
    """
    logger.info(f"Celery worker received job {job_id} for farm {farm_id}")
    
    # Setup asyncio execution loop
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(async_process_farm_raster(job_id, farm_id, polygon))
    except Exception as exc:
        # If transient connection errors occur, retry the task
        logger.warning(f"Retrying task {self.request.id} due to processing exception: {exc}")
        raise self.retry(exc=exc)
