import os
import shutil
import logging
from typing import Any
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.domain.interfaces import StorageService
from app.config import settings

logger = logging.getLogger(__name__)

class R2StorageService(StorageService):
    def __init__(self):
        self.bucket_name = settings.R2_BUCKET_NAME
        self.endpoint_url = settings.R2_ENDPOINT_URL
        self.access_key = settings.R2_ACCESS_KEY_ID
        self.secret_key = settings.R2_SECRET_ACCESS_KEY

        # Check if R2 credentials are fully supplied
        self.use_r2 = all([self.endpoint_url, self.access_key, self.secret_key])

        if self.use_r2:
            try:
                self.s3_client = boto3.client(
                    "s3",
                    endpoint_url=self.endpoint_url,
                    aws_access_key_id=self.access_key,
                    aws_secret_access_key=self.secret_key,
                    config=Config(signature_version="s3v4"),
                    region_name="auto"  # R2 requires region_name auto or us-east-1
                )
                logger.info("Initializing Cloudflare R2 Client successfully")
            except Exception as e:
                logger.error(f"Failed to initialize R2 client: {e}. Falling back to local storage.")
                self.use_r2 = False
        
        if not self.use_r2:
            logger.warning("R2 Cloud Storage is disabled. Using local storage driver.")
            self.local_dir = os.path.join(settings.TEMP_DIR, "processed")
            os.makedirs(self.local_dir, exist_ok=True)

    async def upload_file(self, local_path: str, s3_key: str) -> str:
        """
        Uploads local raster file to R2 or copies to local processed directory.
        """
        if self.use_r2:
            try:
                # Determine Content-Type
                content_type = "image/tiff" if s3_key.endswith((".tif", ".tiff")) else "binary/octet-stream"
                
                self.s3_client.upload_file(
                    local_path,
                    self.bucket_name,
                    s3_key,
                    ExtraArgs={"ContentType": content_type}
                )
                logger.info(f"Successfully uploaded {local_path} to R2 bucket {self.bucket_name} as {s3_key}")
                return f"s3://{self.bucket_name}/{s3_key}"
            except ClientError as e:
                logger.error(f"Error uploading to R2: {e}")
                raise e
        else:
            # Local fallback: copy file to local storage directory under the same key structure
            dest_path = os.path.join(self.local_dir, s3_key)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            shutil.copy2(local_path, dest_path)
            logger.info(f"Local storage fallback: copied {local_path} to {dest_path}")
            return f"local://{s3_key}"

    async def generate_presigned_url(self, s3_key: str, expiration: int = 3600) -> str:
        """
        Generates signed url for R2 or local mock url.
        """
        if self.use_r2:
            try:
                # If a custom public domain prefix is set, we can return that URL directly for simplicity,
                # otherwise return S3-compatible pre-signed URL.
                if settings.R2_PUBLIC_URL_PREFIX:
                    prefix = settings.R2_PUBLIC_URL_PREFIX.rstrip("/")
                    return f"{prefix}/{s3_key}"
                
                url = self.s3_client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket_name, "Key": s3_key},
                    ExpiresIn=expiration
                )
                return url
            except ClientError as e:
                logger.error(f"Error generating presigned url: {e}")
                return f"https://fallback.storage.url/{s3_key}"
        else:
            # In local mode, return a path that our FastAPI app can serve under static files
            # Example: http://localhost:8000/api/v1/static/processed/ndvi/farm_001.tif
            # Since our static route will map settings.TEMP_DIR/processed to /api/v1/static
            return f"/api/v1/static/{s3_key}"
