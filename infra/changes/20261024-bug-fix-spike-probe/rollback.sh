#!/usr/bin/env bash
# Regenerated after each applied step; reverts in reverse order. Usage: rollback.sh [--from N]
set -euo pipefail
FROM=99; [ "${1:-}" = "--from" ] && FROM="${2:?step number}"

# Step 1 — remove ALLOW_PROBE and redeploy (back to a probe-refusing runtime). For the exact v1 image, deploy from integration/bug-fix-agent-wave-a @ 242032d.
if [ "$FROM" -ge 1 ]; then
  python3 - <<'PY'
import json
p='agents/bug-fix/agentcore/agentcore.json'; d=json.load(open(p))
for r in d['runtimes']: r['envVars']=[e for e in r.get('envVars',[]) if e['name']!='ALLOW_PROBE']
open(p,'w').write(json.dumps(d,indent=2)+'\n')
PY
  (cd agents/bug-fix && agentcore deploy -y)
fi
