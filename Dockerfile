FROM python:3.13-slim

# Install dependencies
RUN pip install --no-cache-dir mcp aiohttp requests

# Create app directory
WORKDIR /app

# Copy extension
COPY mcp-croit-ceph.py /app/
RUN chmod +x /app/mcp-croit-ceph.py

# Run as non-root user
RUN useradd -m -u 1000 mcp
USER mcp

# Entry point
ENTRYPOINT ["python", "/app/mcp-croit-ceph.py"]
