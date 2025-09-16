# Publishing to MCP Registry

This document describes the publishing process for the mcp-croit-ceph server.

## Automated Publishing (GitHub Actions)

The project is configured with automated publishing through GitHub Actions. The workflow is triggered when:

1. A new version tag is pushed (e.g., `v0.2.0`)
2. Manually triggered via GitHub Actions UI

### Publishing a New Version

1. Update the version in `server.json`
2. Commit your changes
3. Create and push a version tag:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```

The GitHub Action will automatically:
- Build multi-platform Docker images (amd64/arm64)
- Push to GitHub Container Registry (ghcr.io/croit/mcp-croit-ceph)
- Publish to the MCP Registry using GitHub OIDC authentication

## Repository Setup Requirements

### ✅ Completed
- Created `.github/workflows/publish-mcp.yml` for automated publishing
- Created `.github/workflows/docker-build.yml` for CI testing
- Updated `Dockerfile` with required MCP label
- Configured `server.json` with proper namespace and deployment info

### ⚠️ Required Actions

1. **Enable GitHub Actions** on the GitHub repository:
   - Go to Settings → Actions → General
   - Select "Allow all actions and reusable workflows"

2. **Configure Package Permissions**:
   - Go to Settings → Actions → General
   - Under "Workflow permissions", select "Read and write permissions"

3. **Verify Docker Package Settings**:
   - After first publish, go to Packages → mcp-croit-ceph → Package settings
   - Ensure visibility is set to "Public"

## Manual Publishing (if needed)

If automated publishing fails, you can publish manually:

```bash
# Download MCP publisher
curl -L "https://github.com/modelcontextprotocol/publisher/releases/latest/download/mcp-publisher-linux-amd64.tar.gz" | tar xz

# Login using GitHub
./mcp-publisher login github

# Publish the server
./mcp-publisher publish
```

## Validation

The `server.json` file is validated during the build process. Key requirements:

- **Namespace**: Must use `io.github.croit/*` (matches GitHub organization)
- **Docker Label**: Must include `org.modelcontextprotocol.server` label
- **Registry**: Using GitHub Container Registry (ghcr.io)

## Troubleshooting

1. **Authentication Issues**: Ensure GitHub Actions has proper permissions
2. **Docker Push Fails**: Check package permissions in repository settings
3. **MCP Registry Fails**: Verify namespace matches GitHub organization

## Version Management

Current version: 0.2.0

When updating:
1. Update version in `server.json`
2. Create matching git tag
3. Update changelog if applicable