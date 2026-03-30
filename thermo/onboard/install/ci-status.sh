#!/bin/sh
# Check Thermo Onboard CI (GitHub Actions) status.
# Usage: ./ci-status.sh [count]
# Requires: curl. For private repo, set GITHUB_TOKEN.
COUNT="${1:-5}"
API="https://api.github.com/repos/jovlinger/utils/actions/workflows/thermo-onboard.yml/runs?per_page=$COUNT"
if [ -n "$GITHUB_TOKEN" ]; then
  AUTH="Authorization: Bearer $GITHUB_TOKEN"
else
  AUTH="Accept: application/vnd.github.v3+json"
fi
curl -sS -H "$AUTH" "$API" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception as e:
    print('Error:', e, file=sys.stderr)
    sys.exit(1)
runs = d.get('workflow_runs', [])
if not runs:
    print('No runs found')
    sys.exit(0)
print('Thermo Onboard CI (latest', len(runs), 'runs)')
print('-' * 60)
for r in runs:
    run_id = r.get('run_number', '?')
    status = r.get('status', '?')
    conclusion = r.get('conclusion') or '(running)'
    sha = (r.get('head_sha') or '')[:7]
    title = (r.get('display_title') or r.get('head_commit', {}).get('message') or '')[:50]
    created = r.get('created_at', '')[:19].replace('T', ' ')
    print(f'  #{run_id}  {conclusion:12}  {sha}  {created}  {title}')
print('-' * 60)
print('Details: https://github.com/jovlinger/utils/actions?query=workflow%3A%22Thermo+Onboard%22')
"
