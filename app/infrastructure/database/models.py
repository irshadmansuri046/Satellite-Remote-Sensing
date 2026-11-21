import datetime
from sqlalchemy import Column, String, Float, DateTime, Date, ForeignKey, Text, JSON, Integer
from sqlalchemy.orm import declarative_base, relationship
from geoalchemy2 import Geometry

Base = declarative_base()

class FarmModel(Base):
    __tablename__ = "farms"

    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=True)
    # PostGIS geometry column for Polygon in EPSG:4326
    geometry = Column(Geometry(geometry_type="POLYGON", srid=4326, spatial_index=True), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    jobs = relationship("ProcessingJobModel", back_populates="farm", cascade="all, delete-orphan")
    layers = relationship("RasterLayerModel", back_populates="farm", cascade="all, delete-orphan")
    statistics = relationship("LayerStatisticsModel", back_populates="farm", cascade="all, delete-orphan")


class SatelliteSceneModel(Base):
    __tablename__ = "satellite_scenes"

    id = Column(String, primary_key=True, index=True)  # STAC item ID
    satellite = Column(String, default="Sentinel-2", nullable=False)
    capture_date = Column(Date, nullable=False, index=True)
    cloud_cover = Column(Float, nullable=False)
    geometry = Column(Geometry(geometry_type="POLYGON", srid=4326, spatial_index=True), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)


class ProcessingJobModel(Base):
    __tablename__ = "processing_jobs"

    id = Column(String, primary_key=True, index=True)
    farm_id = Column(String, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, nullable=False, index=True)  # PENDING, RUNNING, COMPLETED, FAILED
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)

    farm = relationship("FarmModel", back_populates="jobs")


class RasterLayerModel(Base):
    __tablename__ = "raster_layers"

    id = Column(String, primary_key=True, index=True)
    farm_id = Column(String, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True)
    layer_type = Column(String, nullable=False)  # ndvi, vegetation, leafNitrogen
    s3_path = Column(String, nullable=False)
    avg_value = Column(Float, nullable=False)
    capture_date = Column(Date, nullable=False, index=True)
    satellite = Column(String, default="Sentinel-2", nullable=False)
    cloud_cover = Column(Float, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    farm = relationship("FarmModel", back_populates="layers")


class LayerStatisticsModel(Base):
    __tablename__ = "layer_statistics"

    id = Column(String, primary_key=True, index=True)
    farm_id = Column(String, ForeignKey("farms.id", ondelete="CASCADE"), nullable=False, index=True)
    capture_date = Column(Date, nullable=False, index=True)
    avg_ndvi = Column(Float, nullable=True)
    vegetation_cover = Column(Float, nullable=True)
    leaf_nitrogen = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    farm = relationship("FarmModel", back_populates="statistics")


class AuditLogModel(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    action = Column(String, nullable=False, index=True)
    farm_id = Column(String, nullable=True, index=True)
    payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
