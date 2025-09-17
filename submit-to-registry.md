# Submit MCP Croit Ceph to Registry

## Automated Publishing
The Docker image is automatically published to GitHub Container Registry when you create a tag.

## Manual Registry Submission
Currently, the MCP Registry requires manual submission via pull request. Here's how:

1. **Fork the Registry Repository**
   ```bash
   gh repo fork modelcontextprotocol/registry --clone
   cd registry
   ```

2. **Add Your Server to the Registry**
   Edit `data/seed.json` and add:
   ```json
   {
     "name": "@croit/mcp-croit-ceph",
     "description": "MCP server for Croit Ceph cluster management - dynamically generates tools from Croit OpenAPI specifications",
     "version": "0.2.1",
     "author": {
       "name": "Croit",
       "url": "https://github.com/croit"
     },
     "homepage": "https://github.com/croit/mcp-croit-ceph",
     "repository": {
       "type": "git",
       "url": "https://github.com/croit/mcp-croit-ceph.git"
     },
     "tags": ["ceph", "storage", "cluster-management", "croit", "openapi"],
     "deployment": {
       "type": "docker",
       "image": "ghcr.io/croit/mcp-croit-ceph:latest"
     }
   }
   ```

3. **Create Pull Request**
   ```bash
   git checkout -b add-croit-mcp-ceph
   git add data/seed.json
   git commit -m "Add @croit/mcp-croit-ceph server"
   git push origin add-croit-mcp-ceph
   gh pr create --title "Add @croit/mcp-croit-ceph server" --body "Adding MCP server for Croit Ceph cluster management"
   ```

## Docker Image
The Docker image is available at:
- `ghcr.io/croit/mcp-croit-ceph:latest`
- `ghcr.io/croit/mcp-croit-ceph:0.2.1`

## Usage
```bash
docker run --rm -i \
  -e CROIT_HOST=http://your-cluster.croit.io:8080 \
  -e CROIT_API_TOKEN=your-token \
  ghcr.io/croit/mcp-croit-ceph:latest
```