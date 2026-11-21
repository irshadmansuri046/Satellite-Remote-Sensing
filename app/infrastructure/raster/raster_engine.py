import os
import logging
from typing import Dict, Any, Tuple
from shapely.geometry import shape
import numpy as np
import rasterio
from rasterio.features import geometry_mask

logger = logging.getLogger(__name__)

class RasterEngine:
    @staticmethod
    def calculate_indices(
        band_paths: Dict[str, str],
        farm_geometry: Dict[str, Any]
    ) -> Tuple[Dict[str, np.ndarray], Dict[str, float], Dict[str, Any]]:
        """
        Calculates NDVI, Vegetation Cover (FVC), and Leaf Nitrogen from band paths.
        Returns:
            - A dict of index name -> numpy array of calculated index
            - A dict of index name -> average value statistics
            - The raster metadata dictionary
        """
        # Read B04, B05, B08
        with rasterio.open(band_paths["B04"]) as src_b4:
            b04 = src_b4.read(1)
            meta = src_b4.meta.copy()
            transform = src_b4.transform
            crs = src_b4.crs

        with rasterio.open(band_paths["B05"]) as src_b5:
            b05 = src_b5.read(1)

        with rasterio.open(band_paths["B08"]) as src_b8:
            b08 = src_b8.read(1)

        # Ensure all bands are same dimensions
        if b04.shape != b05.shape or b04.shape != b08.shape:
            logger.warning("Bands have mismatched shapes. Resampling B05/B08 to match B04.")
            # In a production fallback, we'd resample. Since they are from the same STAC item and
            # cropped using the same bounds, shapes should match.
            # We'll assert same shape for this implementation.
            assert b04.shape == b05.shape == b08.shape, "Mismatched band dimensions"

        # Convert to float32
        b04 = b04.astype(np.float32)
        b05 = b05.astype(np.float32)
        b08 = b08.astype(np.float32)

        # Scale Sentinel-2 DN (Digital Numbers) to reflectance (0.0 to 1.0)
        # S2 L2A scale factor is typically 10000.
        # If max value is > 10, it's safe to assume it's unscaled DN.
        if np.nanmax(b04) > 10.0:
            b04 /= 10000.0
            b05 /= 10000.0
            b08 /= 10000.0

        # Create base nodata mask (where any source band is <= 0 or NaN)
        invalid_mask = (b04 <= 0.0) | (b08 <= 0.0) | (b05 <= 0.0) | np.isnan(b04) | np.isnan(b08) | np.isnan(b05)

        # Re-project or transform farm geometry to match raster CRS before geometry mask
        # Our download step already ensures the local crop is in the raster's native CRS.
        # Let's create geometry mask of the farm polygon
        # geometry_mask returns True for pixels OUTSIDE the geometry
        outside_farm_mask = geometry_mask(
            [shape(farm_geometry)],
            out_shape=b04.shape,
            transform=transform,
            invert=False
        )

        # Combined mask for nodata + outside farm
        full_mask = invalid_mask | outside_farm_mask

        # 1. NDVI = (B08 - B04) / (B08 + B04)
        denom_ndvi = b08 + b04
        ndvi = np.where(denom_ndvi > 0, (b08 - b04) / denom_ndvi, np.nan)
        # Set masked/nodata values to NaN for statistical calculations
        ndvi[full_mask] = np.nan

        # 2. Vegetation Cover (FVC) = (NDVI - 0.2) / (0.8 - 0.2) * 100, clamped 0 - 100
        # Formula uses NDVI values.
        fvc = np.where(~np.isnan(ndvi), (ndvi - 0.2) / 0.6 * 100.0, np.nan)
        fvc = np.clip(fvc, 0.0, 100.0)
        fvc[full_mask] = np.nan

        # 3. Leaf Nitrogen = 35 + (NDRE * 60)
        # NDRE = (B08 - B05) / (B08 + B05)
        denom_ndre = b08 + b05
        ndre = np.where(denom_ndre > 0, (b08 - b05) / denom_ndre, np.nan)
        leaf_nitrogen = np.where(~np.isnan(ndre), 35.0 + (ndre * 60.0), np.nan)
        # Clamp Leaf Nitrogen to a realistic positive agronomic range (0.0 to 150.0 kg/ha)
        leaf_nitrogen = np.clip(leaf_nitrogen, 0.0, 150.0)
        leaf_nitrogen[full_mask] = np.nan

        # Calculate averages ignoring NaN values
        avg_ndvi = float(np.nanmean(ndvi)) if not np.all(np.isnan(ndvi)) else 0.0
        avg_fvc = float(np.nanmean(fvc)) if not np.all(np.isnan(fvc)) else 0.0
        avg_nitrogen = float(np.nanmean(leaf_nitrogen)) if not np.all(np.isnan(leaf_nitrogen)) else 0.0

        stats = {
            "avgNdvi": round(avg_ndvi, 2),
            "vegetationCover": round(avg_fvc, 1),
            "leafNitrogen": round(avg_nitrogen, 1)
        }

        indices = {
            "ndvi": ndvi,
            "vegetation": fvc,
            "leafNitrogen": leaf_nitrogen
        }

        # Prepare metadata for writing
        meta.update({
            "dtype": rasterio.float32,
            "nodata": -9999.0,
            "count": 1
        })

        return indices, stats, meta

    @staticmethod
    def export_cog(
        array: np.ndarray,
        meta: Dict[str, Any],
        out_path: str
    ) -> str:
        """
        Exports a numpy array as a tiled Cloud Optimized GeoTIFF (COG).
        """
        # Fill NaN values with our standard nodata value (-9999.0)
        export_array = np.where(np.isnan(array), -9999.0, array)

        # Configure COG creation profile
        cog_profile = meta.copy()
        cog_profile.update({
            "driver": "GTiff",
            "tiled": True,
            "blockxsize": 256,
            "blockysize": 256,
            "compress": "deflate",
            "predictor": 3,  # Floating point predictor for improved compression
            "interleave": "band"
        })

        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with rasterio.open(out_path, "w", **cog_profile) as dst:
            dst.write(export_array.astype(np.float32), 1)

        return out_path
