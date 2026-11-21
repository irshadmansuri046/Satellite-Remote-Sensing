from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field

class JobStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class ProcessingJob(BaseModel):
    id: str = Field(..., description="Unique job identifier")
    farm_id: str = Field(..., description="Foreign key to the associated farm")
    status: JobStatus = Field(default=JobStatus.PENDING, description="Current processing status")
    error_message: Optional[str] = Field(None, description="Detailed error message if the job failed")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        from_attributes = True
