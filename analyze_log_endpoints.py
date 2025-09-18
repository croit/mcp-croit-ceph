#!/usr/bin/env python3
"""Analyze available log-related endpoints in the OpenAPI spec"""

import json
import re

# Load the OpenAPI spec
with open('openapi.json', 'r') as f:
    spec = json.load(f)

print("=== Searching for log-related endpoints ===\n")

# Search for any endpoints related to logs
log_related = []
audit_related = []
service_related = []

paths = spec.get('paths', {})
for path, methods in paths.items():
    path_lower = path.lower()

    # Check for direct log endpoints
    if 'log' in path_lower:
        for method in methods:
            if method.lower() in ['get', 'post', 'put', 'patch', 'delete']:
                log_related.append(f"{method.upper()} {path}")

    # Check for audit endpoints
    if 'audit' in path_lower:
        for method in methods:
            if method.lower() in ['get', 'post', 'put', 'patch', 'delete']:
                audit_related.append(f"{method.upper()} {path}")

    # Check for service endpoints that might have logs
    if '/services/' in path_lower or '/osd' in path_lower:
        for method in methods:
            if method.lower() in ['get', 'post']:
                operation = methods[method]
                summary = operation.get('summary', '').lower()
                description = operation.get('description', '').lower()
                if 'log' in summary or 'log' in description:
                    service_related.append(f"{method.upper()} {path} - {operation.get('summary', '')}")

# Also check for operations that might be log-related based on their tags or descriptions
for path, methods in paths.items():
    for method, operation in methods.items():
        if method.lower() not in ['get', 'post', 'put', 'patch', 'delete']:
            continue

        # Check tags
        tags = operation.get('tags', [])
        for tag in tags:
            if 'log' in tag.lower():
                endpoint = f"{method.upper()} {path}"
                if endpoint not in log_related:
                    log_related.append(f"{endpoint} [tag: {tag}]")

        # Check operation ID and description
        op_id = operation.get('operationId', '').lower()
        summary = operation.get('summary', '').lower()
        if ('log' in op_id or 'log' in summary) and path not in [e.split()[1] for e in log_related]:
            log_related.append(f"{method.upper()} {path} - {operation.get('summary', '')}")

print("Log-related endpoints:")
for endpoint in sorted(log_related):
    print(f"  {endpoint}")

print(f"\nAudit-related endpoints:")
for endpoint in sorted(audit_related):
    print(f"  {endpoint}")

print(f"\nService endpoints with logs:")
for endpoint in sorted(service_related):
    print(f"  {endpoint}")

# Check for websocket endpoints (they might not be in paths)
print("\n=== Checking schemas for log-related types ===")
schemas = spec.get('components', {}).get('schemas', {})
log_schemas = []
for schema_name, schema_def in schemas.items():
    if 'log' in schema_name.lower():
        log_schemas.append(schema_name)

print("\nLog-related schemas:")
for schema in sorted(log_schemas):
    print(f"  {schema}")
    if schema in ['LogsQLRequest', 'LogsQLRequestType']:
        print(f"    Definition: {json.dumps(schemas[schema], indent=4)[:500]}...")

# Search for any endpoints that use these schemas
print("\n=== Endpoints using log schemas ===")
for path, methods in paths.items():
    for method, operation in methods.items():
        if method.lower() not in ['get', 'post', 'put', 'patch', 'delete']:
            continue

        # Check request body
        if 'requestBody' in operation:
            content = operation['requestBody'].get('content', {})
            for content_type, schema_ref in content.items():
                if 'schema' in schema_ref:
                    ref = str(schema_ref['schema'])
                    if 'LogsQL' in ref:
                        print(f"  {method.upper()} {path} uses {ref}")