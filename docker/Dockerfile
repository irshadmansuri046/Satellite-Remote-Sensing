FROM python:3.12-slim-bookworm

# Prevent python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies for GDAL, PROJ, and PostGIS compatibility
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    binutils \
    libproj-dev \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set up include headers for C/C++ compiler if compiling geospatial extensions from source
ENV CPLUS_INCLUDE_PATH=/usr/include/gdal
ENV C_INCLUDE_PATH=/usr/include/gdal

WORKDIR /app

# Copy dependency manifest
COPY requirements.txt .

# Install dependencies (rasterio, shapely, etc. will utilize precompiled binary wheels on PyPI,
# but system dev headers are available as fallbacks)
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Expose FastAPI server port
EXPOSE 8000
