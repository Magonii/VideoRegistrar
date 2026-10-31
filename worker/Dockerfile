# Образ Ultralytics уже содержит PyTorch с CUDA и OpenCV.
FROM ultralytics/ultralytics:latest
WORKDIR /app
RUN pip install --no-cache-dir httpx
COPY worker ./worker
ENTRYPOINT ["python", "-m", "worker"]
