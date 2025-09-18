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
USER mcp

COPY mcp-croit-ceph.py /app/
COPY token_optimizer.py /app/
COPY croit_log_tools.py /app/
ENV MCP_ARGS=""
ENTRYPOINT ["bash", "-c", "python /app/mcp-croit-ceph.py $MCP_ARGS"]
