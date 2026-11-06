FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run the application. --no-proxy-headers keeps request.client as the TCP
# peer; M2 only honours X-Forwarded-For when TRUSTED_PROXY_IPS matches that
# peer. Uvicorn otherwise defaults proxy_headers=True and trusts 127.0.0.1.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
