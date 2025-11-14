FROM python:3.13-slim

# Add labels for MCP registry validation
LABEL io.modelcontextprotocol.server.name="io.github.croit/mcp-croit-ceph"
LABEL org.opencontainers.image.source="https://github.com/croit/mcp-croit-ceph"
LABEL org.opencontainers.image.description="MCP server for Croit Ceph cluster management"
LABEL org.opencontainers.image.licenses="MIT"

WORKDIR /app
COPY requirements.txt /app/

RUN pip install --no-cache-dir -r requirements.txt
RUN rm requirements.txt

RUN useradd -m -u 1000 mcp

# Final production version with working x-llm-hints integration
RUN echo "Build timestamp: $(date)" > /tmp/build_info
USER mcp

# Copy main entry point
COPY mcp-croit-ceph.py /app/

# Copy source modules
COPY src/ /app/src/

# Copy OpenAPI spec
COPY openapi.json /app/

ENV MCP_ARGS=""
ENTRYPOINT ["bash", "-c", "python /app/mcp-croit-ceph.py $MCP_ARGS"]
