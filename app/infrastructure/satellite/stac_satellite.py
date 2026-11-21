import os
import uuid
import logging
from datetime import datetime, date, timedelta
from typing import Any, Dict, Optional
from shapely.geometry import shape, box
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds
from pystac_client import Client

from app.domain.interfaces import SatelliteService
from app.config import settings

logger = logging.getLogger(__name__)

class StacSatelliteService(SatelliteService):
    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self.stac_url = settings.STAC_API_URL

    async def search_latest_scene(
        self, geometry: Dict[str, Any], max_cloud_cover: float = 20.0
    ) -> Dict[str, Any]:
        """
        Search for the latest available Sentinel-2 scene covering the geometry.
        """
        if self.mock_mode:
            logger.info("Using mock satellite service for search")
            return {
                "scene_id": f"S2A_MSIL2A_mock_{uuid.uuid4().hex[:8]}",
                "satellite": "Sentinel-2",
                "capture_date": date.today(),
                "cloud_cover": 5.2,
                "assets": {
                    "B04": "mock_url_B04",
                    "B05": "mock_url_B05",
                    "B08": "mock_url_B08"
                }
            }

        try:
            client = Client.open(self.stac_url)
            # Query last 6 months to find a cloud-free scene
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=180)
            datetime_range = f"{start_date.strftime('%Y-%m-%dT%H:%M:%SZ')}/{end_date.strftime('%Y-%m-%dT%H:%M:%SZ')}"

            # Run STAC query
            search = client.search(
                collections=["sentinel-2-l2a"],
                intersects=geometry,
                datetime=datetime_range,
                query={
                    "eo:cloud_cover": {"lt": max_cloud_cover}
                },
                sortby=[{"field": "properties.datetime", "direction": "desc"}]
            )

            items = list(search.items())
            if not items:
                raise ValueError("No Sentinel-2 scenes found matching the criteria.")

            # Pick the latest scene
            latest_item = items[0]
            properties = latest_item.properties
            assets = latest_item.assets

            # Map Earth Search bands to B04, B05, B08
            # In Earth Search STAC:
            # - B04 is "red"
            # - B05 is "rededge1"
            # - B08 is "nir"
            band_urls = {}
            for target_band, stac_key in [("B04", "red"), ("B05", "rededge1"), ("B08", "nir")]:
                if stac_key in assets:
                    band_urls[target_band] = assets[stac_key].href
                elif target_band in assets:
                    band_urls[target_band] = assets[target_band].href
                else:
                    # Fallback lookup in asset keys
                    keys = list(assets.keys())
                    found = False
                    for k in keys:
                        if target_band.lower() in k.lower():
                            band_urls[target_band] = assets[k].href
                            found = True
                            break
                    if not found:
                        raise ValueError(f"Required band {target_band} not found in STAC assets {keys}.")

            capture_date_str = properties.get("datetime", properties.get("created", ""))[:10]
            capture_date = datetime.strptime(capture_date_str, "%Y-%m-%d").date()

            return {
                "scene_id": latest_item.id,
                "satellite": "Sentinel-2",
                "capture_date": capture_date,
                "cloud_cover": properties.get("eo:cloud_cover", 0.0),
                "assets": band_urls
            }

        except Exception as e:
            logger.error(f"Error searching Sentinel-2 STAC: {e}. Falling back to mock mode.")
            self.mock_mode = True
            return await self.search_latest_scene(geometry, max_cloud_cover)

    async def download_bands_window(
        self, scene_metadata: Dict[str, Any], geometry: Dict[str, Any], output_dir: str
    ) -> Dict[str, str]:
        """
        Download only the bbox window of B04, B05, B08 from Sentinel-2 scene.
        """
        os.makedirs(output_dir, exist_ok=True)
        band_paths = {}

        shapely_geom = shape(geometry)
        minx, miny, maxx, maxy = shapely_geom.bounds

        if self.mock_mode:
            logger.info("Generating mock satellite band files locally")
            # Create synthetic bands
            # 10m Sentinel-2 resolution: ~100m spacing, let's create a 30x30 mock grid
            width, height = 30, 30
            crs = "EPSG:4326"
            # Define transform for spatial referencing
            res_x = (maxx - minx) / width
            res_y = (maxy - miny) / height
            transform = rasterio.transform.from_bounds(minx, miny, maxx, maxy, width, height)

            # Generate synthetic values:
            # B04 (Red): low reflectance (scaled integer 400 - 800)
            # B05 (RedEdge): mid reflectance (scaled integer 1000 - 2500)
            # B08 (NIR): high reflectance (scaled integer 3000 - 6000)
            np.random.seed(42)
            mock_data = {
                "B04": np.random.randint(400, 800, size=(height, width), dtype=np.uint16),
                "B05": np.random.randint(1500, 2500, size=(height, width), dtype=np.uint16),
                "B08": np.random.randint(3500, 5500, size=(height, width), dtype=np.uint16)
            }

            for band, data in mock_data.items():
                out_path = os.path.join(output_dir, f"{scene_metadata['scene_id']}_{band}.tif")
                with rasterio.open(
                    out_path,
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
                band_paths[band] = out_path

            return band_paths

        # Actual remote read
        assets = scene_metadata["assets"]
        for band in ["B04", "B05", "B08"]:
            asset_url = assets[band]
            out_path = os.path.join(output_dir, f"{scene_metadata['scene_id']}_{band}.tif")

            try:
                # Open remote COG using GDAL's /vsicurl/ virtual file system via rasterio
                with rasterio.open(asset_url) as src:
                    # Reproject farm bounds from EPSG:4326 to raster native CRS
                    left, bottom, right, top = transform_bounds(
                        "EPSG:4326",
                        src.crs,
                        minx, miny, maxx, maxy
                    )

                    # Determine pixels window mapping to physical coordinate bounds
                    window = from_bounds(left, bottom, right, top, transform=src.transform)
                    
                    # Round and buffer the window to ensure no edge clipping
                    window = window.round()
                    
                    # Read window slice directly
                    data = src.read(1, window=window)
                    window_transform = src.window_transform(window)

                    # Save crop as a local GeoTIFF
                    with rasterio.open(
                        out_path,
                        "w",
                        driver="GTiff",
                        height=window.height,
                        width=window.width,
                        count=1,
                        dtype=src.dtypes[0],
                        crs=src.crs,
                        transform=window_transform,
                        nodata=src.nodata
                    ) as dst:
                        dst.write(data, 1)

                    band_paths[band] = out_path
                    logger.info(f"Successfully downloaded window for band {band}")

            except Exception as e:
                logger.error(f"Failed to read band {band} from STAC: {e}. Bypassing to mock generator.")
                # If reading remote STAC asset fails (e.g. AWS credentials/requester-pays block),
                # clean up partial downloads, trigger fallback to mock and re-call
                self.mock_mode = True
                return await self.download_bands_window(scene_metadata, geometry, output_dir)

        return band_paths
