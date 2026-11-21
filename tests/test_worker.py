import os
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from app.workers.tasks import async_process_farm_raster
from app.domain.entities.job import JobStatus
from app.domain.entities.layer import LayerType
from datetime import date

@pytest.mark.asyncio
@patch("app.workers.tasks.AsyncSessionLocal")
@patch("app.workers.tasks.StacSatelliteService")
@patch("app.workers.tasks.R2StorageService")
@patch("app.workers.tasks.RasterEngine")
async def test_async_process_farm_raster_pipeline(
    mock_raster_engine,
    mock_r2_class,
    mock_stac_class,
    mock_session_class,
    sample_polygon
):
    # 1. Setup session mocks
    mock_session = AsyncMock()
    mock_session_class.return_value.__aenter__.return_value = mock_session

    # 2. Setup mock services
    mock_stac = MagicMock()
    mock_stac.search_latest_scene = AsyncMock(return_value={
        "scene_id": "S2A_scene_test",
        "satellite": "Sentinel-2",
        "capture_date": date(2026, 6, 18),
        "cloud_cover": 5.0,
        "assets": {}
    })
    mock_stac.download_bands_window = AsyncMock(return_value={
        "B04": "local_B04.tif",
        "B05": "local_B05.tif",
        "B08": "local_B08.tif"
    })
    mock_stac_class.return_value = mock_stac

    mock_r2 = MagicMock()
    mock_r2.upload_file = AsyncMock(return_value="s3://processed/test.tif")
    mock_r2_class.return_value = mock_r2

    # 3. Setup mock raster calculations
    mock_raster_engine.calculate_indices.return_value = (
        {
            "ndvi": "ndvi_array",
            "vegetation": "fvc_array",
            "leafNitrogen": "nitrogen_array"
        },
        {
            "avgNdvi": 0.74,
            "vegetationCover": 82.0,
            "leafNitrogen": 61.0
        },
        {"meta": "meta"}
    )
    mock_raster_engine.export_cog.return_value = "cog_path.tif"

    # Patch the repository helpers to mock DB calls
    with patch("app.workers.tasks.SqlJobRepository") as mock_job_repo_class, \
         patch("app.workers.tasks.SqlRasterRepository") as mock_raster_repo_class:
        
        mock_job_repo = MagicMock()
        mock_job_repo.update_status = AsyncMock()
        mock_job_repo_class.return_value = mock_job_repo

        mock_raster_repo = MagicMock()
        mock_raster_repo.save_layer = AsyncMock()
        mock_raster_repo.save_statistics = AsyncMock()
        mock_raster_repo_class.return_value = mock_raster_repo

        # 4. Run pipeline
        job_id = "test-job-123"
        farm_id = "test-farm-123"
        
        await async_process_farm_raster(job_id, farm_id, sample_polygon)

        # 5. Assert database updates
        # Job should set status to RUNNING initially, and then COMPLETED
        mock_job_repo.update_status.assert_any_call(job_id, JobStatus.RUNNING)
        mock_job_repo.update_status.assert_any_call(job_id, JobStatus.COMPLETED)
        
        # Check layers saved
        assert mock_raster_repo.save_layer.call_count == 3
        
        # Check statistics saved
        mock_raster_repo.save_statistics.assert_called_once_with(
            farm_id=farm_id,
            capture_date=date(2026, 6, 18),
            avg_ndvi=0.74,
            vegetation_cover=82.0,
            leaf_nitrogen=61.0
        )
