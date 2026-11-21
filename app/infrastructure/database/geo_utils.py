from typing import Any, Dict
from shapely.geometry import shape, mapping
from geoalchemy2.shape import from_shape, to_shape
from geoalchemy2.elements import WKBElement

def geojson_to_geometry(geojson: Dict[str, Any]) -> Any:
    """
    Converts GeoJSON dictionary to a GeoAlchemy2 geometry element.
    """
    shapely_shape = shape(geojson)
    return from_shape(shapely_shape, srid=4326)

def geometry_to_geojson(geom: Any) -> Dict[str, Any]:
    """
    Converts GeoAlchemy2 geometry element (WKBElement or WKTElement) to GeoJSON dictionary.
    """
    if isinstance(geom, WKBElement):
        shapely_shape = to_shape(geom)
        return mapping(shapely_shape)
    elif hasattr(geom, "geom_type"):
        return mapping(geom)
    raise ValueError(f"Unsupported geometry type: {type(geom)}")
