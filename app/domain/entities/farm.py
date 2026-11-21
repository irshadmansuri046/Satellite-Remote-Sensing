from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class Farm(BaseModel):
    id: str = Field(..., description="Unique identifier for the farm")
    name: Optional[str] = Field(None, description="Optional name for the farm")
    # Store geometry as GeoJSON dict, or it can be a shapely object. 
    # For serialization ease in domain entities, we use GeoJSON dict.
    geometry: Dict[str, Any] = Field(..., description="GeoJSON polygon geometry of the farm")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True
        arbitrary_types_allowed = True
