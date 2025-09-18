#!/usr/bin/env python3
"""Simple check for logs category in OpenAPI spec"""

import json
from collections import Counter

# Load the OpenAPI spec
with open('openapi.json', 'r') as f:
    spec = json.load(f)

# Analyze tags/categories
tag_counter = Counter()
category_endpoints = {}

paths = spec.get('paths', {})
for path, methods in paths.items():
    for method, operation in methods.items():
        if method.lower() not in ["get", "post", "put", "delete", "patch"]:
            continue

        if operation.get('deprecated', False):
            continue

        tags = operation.get('tags', [])
        for tag in tags:
            tag_counter[tag] += 1
            if tag not in category_endpoints:
                category_endpoints[tag] = []

            # Store endpoint info
            endpoint_info = {
                'path': path,
                'method': method,
                'summary': operation.get('summary', ''),
                'has_hints': 'x-llm-hints' in operation
            }
            category_endpoints[tag].append(endpoint_info)

# Sort categories by frequency
sorted_categories = sorted(tag_counter.items(), key=lambda x: x[1], reverse=True)

print("=== Tag/Category Analysis ===\n")
print("Top 20 categories by endpoint count:")
for i, (tag, count) in enumerate(sorted_categories[:20], 1):
    print(f"{i:2}. {tag:20} - {count:3} endpoints")

# Check specifically for logs
print("\n=== Logs Category Details ===")
if 'logs' in category_endpoints:
    print(f"✅ 'logs' category exists with {len(category_endpoints['logs'])} endpoints:")
    for ep in category_endpoints['logs']:
        hints = "✓" if ep['has_hints'] else "✗"
        print(f"   [{hints}] {ep['method'].upper():6} {ep['path']:30} - {ep['summary']}")
else:
    print("❌ 'logs' category does not exist")

# Check admin-only categories list
admin_categories = [
    "maintenance", "servers", "ipmi", "config", "hooks",
    "change-requests", "config-templates"
]

print(f"\n=== Category Ranking for Hybrid Mode ===")
print(f"'logs' rank: #{next((i+1 for i, (tag, _) in enumerate(sorted_categories) if tag == 'logs'), 'Not found')}")
print(f"Would 'logs' be in top 10? {('logs' in [tag for tag, _ in sorted_categories[:10]])}")

# Show what would be selected for hybrid mode (top 10 non-admin categories)
non_admin_categories = [
    (tag, count) for tag, count in sorted_categories
    if tag not in admin_categories
][:10]

print(f"\nTop 10 non-admin categories (selected for hybrid mode):")
for i, (tag, count) in enumerate(non_admin_categories, 1):
    selected = "✅" if tag == 'logs' else ""
    print(f"{i:2}. {tag:20} - {count:3} endpoints {selected}")