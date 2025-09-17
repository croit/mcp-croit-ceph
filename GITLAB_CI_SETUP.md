# GitLab CI Setup for MCP Registry Publishing

## Required CI/CD Variables

To enable Docker Hub pushing and MCP Registry publishing, configure these variables in your GitLab project settings:

### Docker Hub Variables
- `DOCKERHUB_USER`: Your Docker Hub username
- `DOCKERHUB_PASSWORD`: Your Docker Hub password or access token

### MCP Registry Variables
- `MCP_GITHUB_TOKEN`: GitHub Personal Access Token with `public_repo` scope
  - Create at: https://github.com/settings/tokens
  - Required for publishing to MCP Registry from GitLab

## Pipeline Stages

1. **lint**: Checks Python code formatting with Black
2. **build**:
   - Builds Docker image
   - Pushes to GitLab Container Registry
   - Pushes to Docker Hub with version tags (0.2.0, latest, and git tag if present)
3. **publish**:
   - Downloads MCP publisher tool
   - Authenticates with GitHub token
   - Publishes server.json to MCP Registry
   - Only runs on tags or manual trigger

## Version Management

The version `0.2.9` is defined in:
- `.gitlab-ci.yml` (MCP_VERSION variable)
- `server.json` (packages[0].version field)

When updating the version, change it in both places.

## Manual Publishing

To manually trigger the MCP Registry publishing:
1. Go to GitLab CI/CD → Pipelines
2. Click "Run pipeline"
3. Select the branch/tag
4. The publish stage will run

## Docker Hub Image

The image is published to Docker Hub as:
- `croit/mcp-croit-ceph:0.2.9` (version tag)
- `croit/mcp-croit-ceph:latest` (latest tag)
- `croit/mcp-croit-ceph:<git-tag>` (when pushing git tags)