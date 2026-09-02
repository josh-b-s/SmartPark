# Slim base keeps the image smaller. ultralytics pulls in torch, which is
# large regardless, but no point adding extra bulk on top of that.
FROM python:3.11-slim

WORKDIR /app

# opencv-python (a dependency of ultralytics) needs these system libraries
# even though this is a headless container with no display. Without them,
# `import cv2` fails at model-load time with errors like
# "libxcb.so.1: cannot open shared object file".
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first so Docker can cache this layer and skip the
# (slow) pip install on rebuilds where only app code changed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code and the sample camera images. These are small and static, so
# they're fine to bake into the image.
COPY app/ ./app
COPY images/ ./images

# Deliberately NOT copying model/ here. Per the assignment's requirement
# that the model be updatable without rebuilding the image, weights get
# mounted in at container/pod startup instead (see README "Run with Docker"
# section for the `-v` flag, or the k8s manifests in a later step for the
# equivalent volume mount).
RUN mkdir -p /app/model

ENV SMARTPARK_IMAGE_DIR=/app/images
ENV SMARTPARK_MODEL_PATH=/app/model/model.pt

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
