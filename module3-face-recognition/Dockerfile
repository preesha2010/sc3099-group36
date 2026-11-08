FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

# Runtime libraries for the bundled OpenCV/MediaPipe wheels.
RUN apt-get update && apt-get install -y \
    --no-install-recommends \
    libgl1 \
    libgomp1 \
    libstdc++6 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app ./app
COPY models/sface.onnx models/yunet.onnx ./models/

RUN useradd --uid 10001 --create-home saiv
RUN mkdir /app/state && chown saiv:saiv /app/state
ENV FACE_TEMPLATE_KEY_PATH=/app/state/template.key
VOLUME /app/state
USER saiv

# Expose port
EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health', timeout=3)" || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
