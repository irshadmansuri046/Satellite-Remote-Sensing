from datetime import date, datetime
from enum import Enum
from typing import Dict, Optional, Any
from pydantic import BaseModel, Field

class LayerType(str, Enum):
    NDVI = "ndvi"
    VEGETATION = "vegetation"
    LEAF_NITROGEN = "leafNitrogen"

class RasterLayer(BaseModel):
    id: str = Field(..., description="Unique layer identifier")
    farm_id: str = Field(..., description="Foreign key to the associated farm")
    layer_type: LayerType = Field(..., description="The type of the processed raster index")
    s3_path: str = Field(..., description="Path of the raster object in R2 storage")
    avg_value: float = Field(..., description="Computed average value of the layer within the farm boundary")
    capture_date: date = Field(..., description="Acquisition date of the satellite scene")
    satellite: str = Field("Sentinel-2", description="Satellite source name")
    cloud_cover: float = Field(..., description="Percentage of cloud cover in the source scene")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True
