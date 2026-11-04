# Pinned, so apt package names cannot shift under a new Debian release.
FROM python:3.11-slim-bookworm

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
# pip defaults to 5 retries and a 15 second timeout, which is not enough
# on a connection that drops mid-transfer. A truncated response from the
# package index surfaces as a JSONDecodeError deep inside pip's resolver
# and reads like a broken requirements file rather than a dropped
# connection, so give it room to retry instead.
ENV PIP_RETRIES=10 \
    PIP_DEFAULT_TIMEOUT=100

COPY requirements.txt .
# Retried, and the cache is kept between attempts on purpose.
#
# On a connection that truncates or corrupts responses, a single pip run
# is a coin flip: a mangled wheel fails its checksum and pip reports
# "THESE PACKAGES DO NOT MATCH THE HASHES", which reads like tampering
# rather than a bad transfer. Re-running almost always succeeds because
# it fetches the file again.
#
# Dropping --no-cache-dir means a retry only re-fetches what actually
# failed instead of starting the whole download over. The cache is purged
# afterwards so it does not ship inside the image.
RUN n=0; until pip install -r requirements.txt; do \
        n=$((n+1)); \
        if [ $n -ge 5 ]; then echo "pip failed 5 times, giving up"; exit 1; fi; \
        echo "pip attempt $n failed, retrying in 15s"; \
        sleep 15; \
    done; \
    pip cache purge >/dev/null 2>&1 || true; rm -rf /root/.cache/pip

# Copy application code
COPY . .

# main.py does `from app import api, theme`, and the package lives at
# /app/app. Streamlit puts the SCRIPT's directory on sys.path, not the
# working directory, and the `streamlit` console script does not add the
# working directory either. So /app is on the path for nobody and the
# import fails with ModuleNotFoundError at first page load.
#
# Running it as `python -m streamlit` would also work, because -m adds the
# working directory, and that is why it works outside Docker. Setting the
# path explicitly does not depend on how it is launched.
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8501

# Run the application
CMD ["streamlit", "run", "app/main.py", "--server.port=8501", "--server.address=0.0.0.0"]
