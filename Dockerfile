FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt /app/

RUN pip install --no-cache-dir -r requirements.txt
RUN rm requirements.txt

RUN useradd -m -u 1000 mcp
USER mcp

COPY mcp-croit-ceph.py /app/
ENV MCP_ARGS=""
ENTRYPOINT ["bash", "-c", "python /app/mcp-croit-ceph.py $MCP_ARGS"]
