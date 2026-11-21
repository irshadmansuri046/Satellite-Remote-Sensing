import os
import tempfile
import pytest
import numpy as np
import rasterio
from shapely.geometry import mapping, Polygon
from app.infrastructure.raster.raster_engine import RasterEngine

def create_dummy_raster(file_path: str, data: np.ndarray, transform, crs="EPSG:4326"):
    """
    Helper to write a temporary GeoTIFF band.
    """
    height, width = data.shape
    with rasterio.open(
        file_path,
        "w",
        driver="GTiff",
        height=height,
        width=width,
        count=1,
        dtype=rasterio.uint16,
        crs=crs,
        transform=transform,
    ) as dst:
        dst.write(data, 1)

def test_raster_engine_calculations():
    # Setup simple geometry (a square polygon from lon 10 to 20, lat 10 to 20)
    poly = Polygon([(10, 10), (10, 20), (20, 20), (20, 10), (10, 10)])
    geometry_dict = mapping(poly)

    # Setup 10x10 grid raster covering bounds 5 to 25 lon/lat
    # Centered squarely within bounds
    transform = rasterio.transform.from_bounds(5, 5, 25, 25, 10, 10)

    # B04 (Red): low reflectance (DN: 500)
    # B05 (RedEdge): mid reflectance (DN: 2000)
    # B08 (NIR): high reflectance (DN: 6000)
    # DN values of 500/10000 = 0.05, 2000/10000 = 0.20, 6000/10000 = 0.60
    b04_data = np.full((10, 10), 500, dtype=np.uint16)
    b05_data = np.full((10, 10), 2000, dtype=np.uint16)
    b08_data = np.full((10, 10), 6000, dtype=np.uint16)

    # Create temporary files
    with tempfile.TemporaryDirectory() as temp_dir:
        b4_path = os.path.join(temp_dir, "b4.tif")
        b5_path = os.path.join(temp_dir, "b5.tif")
        b8_path = os.path.join(temp_dir, "b8.tif")

        create_dummy_raster(b4_path, b04_data, transform)
        create_dummy_raster(b5_path, b05_data, transform)
        create_dummy_raster(b8_path, b08_data, transform)

        band_paths = {"B04": b4_path, "B05": b5_path, "B08": b8_path}

        # Run calculation
        indices, stats, meta = RasterEngine.calculate_indices(band_paths, geometry_dict)

        # Expected indices:
        # NDVI = (0.60 - 0.05) / (0.60 + 0.05) = 0.55 / 0.65 = 0.846
        # FVC = (0.846 - 0.2) / 0.6 * 100 = 0.646 / 0.6 * 100 = 107.6% (clamped to 100%)
        # NDRE = (0.60 - 0.20) / (0.60 + 0.20) = 0.40 / 0.80 = 0.50
        # Nitrogen = 35 + (0.50 * 60) = 35 + 30 = 65.0 kg/ha
        
        assert "ndvi" in indices
        assert "vegetation" in indices
        assert "leafNitrogen" in indices

        # Test statistics averages
        assert stats["avgNdvi"] == pytest.approx(0.85, abs=0.01)
        assert stats["vegetationCover"] == pytest.approx(100.0, abs=0.1)
        assert stats["leafNitrogen"] == pytest.approx(65.0, abs=0.1)

        # Verify metadata dtype & nodata configuration
        assert meta["dtype"] == rasterio.float32
        assert meta["nodata"] == -9999.0

        # Test COG export
        out_cog_path = os.path.join(temp_dir, "ndvi_cog.tif")
        RasterEngine.export_cog(indices["ndvi"], meta, out_cog_path)
        assert os.path.exists(out_cog_path)

        # Re-open exported COG and check options
        with rasterio.open(out_cog_path) as src:
            assert src.profile["tiled"] is True
            assert src.profile["compress"] == "deflate"
            assert src.nodata == -9999.0
            data = src.read(1)
            # Check shape matches input
            assert data.shape == (10, 10)
            # Check values are computed inside poly and masked outside
            # The geometry covers pixels inside coordinates (10,10) to (20,20).
            # The raster spans from (5,5) to (25,25).
            # Some edge pixels should be nodata (-9999.0)
            assert np.any(data == -9999.0)
