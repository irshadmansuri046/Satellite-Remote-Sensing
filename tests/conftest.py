import pytest
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient

# Mock test geometry (polygon over a farm)
@pytest.fixture
def sample_polygon():
    return {
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

@pytest.fixture
def mock_farm_repo():
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.get_by_id = AsyncMock()
    return repo

@pytest.fixture
def mock_job_repo():
    repo = MagicMock()
    repo.save = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.update_status = AsyncMock()
    return repo

@pytest.fixture
def mock_raster_repo():
    repo = MagicMock()
    repo.save_layer = AsyncMock()
    repo.get_layers_by_farm = AsyncMock()
    repo.get_latest_statistics = AsyncMock()
    repo.save_statistics = AsyncMock()
    return repo

@pytest.fixture
def mock_storage_service():
    srv = MagicMock()
    srv.upload_file = AsyncMock(return_value="s3://farm-rasters/test.tif")
    srv.generate_presigned_url = AsyncMock(return_value="https://presigned.url/test.tif")
    return srv
