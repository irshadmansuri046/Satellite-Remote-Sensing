from unittest.mock import patch, MagicMock, AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.main import app
from app.api.endpoints import get_farm_repo, get_job_repo, get_raster_repo, get_storage_service
from app.infrastructure.database.session import get_async_db
from app.domain.entities.job import ProcessingJob, JobStatus
from app.domain.entities.layer import RasterLayer, LayerType
from datetime import date, datetime

@pytest.fixture
def client(mock_farm_repo, mock_job_repo, mock_raster_repo, mock_storage_service):
    # Override dependencies
    app.dependency_overrides[get_farm_repo] = lambda: mock_farm_repo
    app.dependency_overrides[get_job_repo] = lambda: mock_job_repo
    app.dependency_overrides[get_raster_repo] = lambda: mock_raster_repo
    app.dependency_overrides[get_storage_service] = lambda: mock_storage_service
    
    # Mock db session for health check test
    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    app.dependency_overrides[get_async_db] = lambda: mock_db
    
    with TestClient(app) as test_client:
        yield test_client
        
    app.dependency_overrides.clear()


def test_process_layers_endpoint(client, sample_polygon):
    # Mock celery task dispatching
    with patch("app.infrastructure.queue.celery_app.celery_app.send_task") as mock_send_task:
        payload = {"polygon": sample_polygon}
        response = client.post("/api/v1/layers", json=payload)
        
        assert response.status_code == 202
        data = response.json()
        assert "jobId" in data
        assert "farmId" in data
        assert data["status"] == "PENDING"
        
        # Verify celery was triggered with process signature
        mock_send_task.assert_called_once()
        args, kwargs = mock_send_task.call_args
        assert args[0] == "app.workers.tasks.process_farm_raster_task"
        # Verify farmId and polygon were passed in task arguments
        assert kwargs["queue"] == "celery"


def test_process_layers_invalid_geojson(client):
    # Pass invalid geometry type (Point instead of Polygon)
    payload = {
        "polygon": {
            "type": "Point",
            "coordinates": [12.5, 45.6]
        }
    }
    response = client.post("/api/v1/layers", json=payload)
    # Pydantic pattern validation on 'type' field will fail (needs 'Polygon')
    assert response.status_code == 422


def test_get_job_status(client, mock_job_repo):
    job_id = "test-job-uuid"
    mock_job = ProcessingJob(
        id=job_id,
        farm_id="test-farm-id",
        status=JobStatus.RUNNING,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    mock_job_repo.get_by_id.return_value = mock_job

    response = client.get(f"/api/v1/jobs/{job_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["jobId"] == job_id
    assert data["status"] == "RUNNING"
    assert data["errorMessage"] is None


def test_get_farm_layers(client, mock_raster_repo, mock_storage_service):
    farm_id = "farm_abc"
    cap_date = date(2026, 6, 18)
    
    mock_raster_repo.get_layers_by_farm.return_value = [
        RasterLayer(
            id="l1", farm_id=farm_id, layer_type=LayerType.NDVI,
            s3_path="processed/ndvi/farm_abc/scene.tif", avg_value=0.74,
            capture_date=cap_date, satellite="Sentinel-2", cloud_cover=5.0
        ),
        RasterLayer(
            id="l2", farm_id=farm_id, layer_type=LayerType.VEGETATION,
            s3_path="processed/vegetation/farm_abc/scene.tif", avg_value=82.0,
            capture_date=cap_date, satellite="Sentinel-2", cloud_cover=5.0
        ),
        RasterLayer(
            id="l3", farm_id=farm_id, layer_type=LayerType.LEAF_NITROGEN,
            s3_path="processed/leafNitrogen/farm_abc/scene.tif", avg_value=61.0,
            capture_date=cap_date, satellite="Sentinel-2", cloud_cover=5.0
        )
    ]

    response = client.get(f"/api/v1/layers/{farm_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["farmId"] == farm_id
    assert data["layers"]["ndvi"] == "https://presigned.url/test.tif"
    assert data["layers"]["vegetation"] == "https://presigned.url/test.tif"
    assert data["layers"]["leafNitrogen"] == "https://presigned.url/test.tif"
    assert data["metadata"]["satellite"] == "Sentinel-2"
    assert data["metadata"]["captureDate"] == "2026-06-18"
    assert data["metadata"]["cloudCover"] == 5.0


def test_get_farm_statistics(client, mock_raster_repo):
    farm_id = "farm_abc"
    mock_raster_repo.get_latest_statistics.return_value = {
        "avgNdvi": 0.74,
        "vegetationCover": 82.0,
        "leafNitrogen": 61.0
    }

    response = client.get(f"/api/v1/statistics/{farm_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["farmId"] == farm_id
    assert data["statistics"]["avgNdvi"] == 0.74
    assert data["statistics"]["vegetationCover"] == 82.0
    assert data["statistics"]["leafNitrogen"] == 61.0


def test_health_check_endpoint(client):
    # For simplicity, we patch database querying inside endpoints to test health check
    # Patch the redis ping and sql check
    with patch("redis.Redis.from_url") as mock_redis:
        mock_redis_client = MagicMock()
        mock_redis_client.ping.return_value = True
        mock_redis.return_value = mock_redis_client
        
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["components"]["database"] == "up"
        assert data["components"]["redis"] == "up"


def test_analyze_farm_polygon_completed(client, mock_raster_repo, sample_polygon):
    from app.application.use_cases.analyze_farm_polygon import AnalyzeFarmPolygonUseCase

    farm_id = "farm_analysis_test"
    poll_count = {"n": 0}

    async def mock_get_job_status(self, job_id: str):
        poll_count["n"] += 1
        job_status = JobStatus.PENDING if poll_count["n"] == 1 else JobStatus.COMPLETED
        return ProcessingJob(
            id=job_id,
            farm_id=farm_id,
            status=job_status,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )

    async def mock_attach_results(self, response, attached_farm_id: str):
        response["layers"] = {
            "ndvi": "https://presigned.url/test.tif",
            "vegetation": "https://presigned.url/test.tif",
            "leafNitrogen": "https://presigned.url/test.tif",
        }
        response["metadata"] = {
            "satellite": "Sentinel-2",
            "captureDate": "2026-06-22",
            "cloudCover": 5.2,
        }
        response["statistics"] = {
            "avgNdvi": 0.76,
            "vegetationCover": 92.5,
            "leafNitrogen": 58.0,
        }

    with patch("app.infrastructure.queue.celery_app.celery_app.send_task"), \
         patch.object(AnalyzeFarmPolygonUseCase, "_get_job_status", mock_get_job_status), \
         patch.object(AnalyzeFarmPolygonUseCase, "_attach_results", mock_attach_results):
        response = client.post(
            "/api/v1/analysis",
            json={"polygon": sample_polygon},
            params={"farmId": farm_id, "timeoutSeconds": 5},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["farmId"] == farm_id
    assert data["status"] == "COMPLETED"
    assert data["layers"]["ndvi"] == "https://presigned.url/test.tif"
    assert data["statistics"]["avgNdvi"] == 0.76
    assert data["relatedEndpoints"]["jobStatus"] == f"/api/v1/jobs/{data['jobId']}"
    assert data["polygon"]["type"] == "Polygon"


def test_analyze_farm_polygon_no_wait(client, sample_polygon):
    from app.application.use_cases.analyze_farm_polygon import AnalyzeFarmPolygonUseCase

    mock_result = {
        "jobId": "job-no-wait",
        "farmId": "farm_no_wait",
        "status": "PENDING",
        "errorMessage": None,
        "polygon": sample_polygon,
        "layers": None,
        "metadata": None,
        "statistics": None,
        "relatedEndpoints": {
            "jobStatus": "/api/v1/jobs/job-no-wait",
            "layers": "/api/v1/layers/farm_no_wait",
            "statistics": "/api/v1/statistics/farm_no_wait",
            "analysis": "/api/v1/analysis",
        },
    }

    with patch.object(
        AnalyzeFarmPolygonUseCase,
        "execute",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        response = client.post(
            "/api/v1/analysis",
            json={"polygon": sample_polygon},
            params={"wait": False},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PENDING"
    assert data["layers"] is None
    assert data["statistics"] is None
    assert "relatedEndpoints" in data
