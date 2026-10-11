#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "$0")/../.." && pwd)
platform=$(cd -- "$root/../aws-platform/platform" && pwd)
venv=${1:-$HOME/.venvs/platform}
source "$venv/bin/activate"
export ANSIBLE_CONFIG="$platform/ansible.cfg"
export ANSIBLE_ROLES_PATH="$platform/roles"
unset ANSIBLE_INVENTORY ANSIBLE_VAULT_PASSWORD_FILE
bash -n "$root/infra/bootstrap/run.sh"
bash -n "$root/infra/bootstrap/mount-data.sh"
ansible-playbook -i "$root/infra/tests/inventory.json" "$root/infra/bootstrap/front.yml" --syntax-check
ansible-playbook -i "$root/infra/tests/inventory.json" "$root/infra/bootstrap/clusters.yml" --syntax-check
python - "$root" <<'PY'
import json,sys,pathlib,yaml
from jinja2 import Environment,StrictUndefined
r=pathlib.Path(sys.argv[1])
env=Environment(undefined=StrictUndefined)
t=(r/'infra/bootstrap/templates/front.conf.j2').read_text()
render=env.from_string(t).render(test_client_cidrs=['192.0.2.10/32'],groups={'game':['game'],'ad':['ad']},hostvars={'game':{'ip':'10.10.10.30'},'ad':{'ip':'10.10.10.31'}})
assert 'allow 192.0.2.10/32;' in render and 'deny all;' in render
assert 'proxy_pass http://10.10.10.30:8000;' in render
assert 'proxy_pass http://10.10.10.31:8000;' in render
assert 'proxy_set_header Upgrade $http_upgrade;' in render
assert 'location /static/' in render and 'location /ads/' in render
small=yaml.safe_load((r/'infra/bootstrap/vars/small.yml').read_text())
# 2GiB 모델에서 OS에 보이는 RAM을 보수적으로 1900MiB로 놓은 설정 검사다.
worker=1900-small['spark_os_reserve_mb']-2*small['spark_daemon_mb']-small['zookeeper_heap_mb']
assert worker>=small['spark_worker_min_mb']
top=json.loads((r/'infra/config/topology.tfvars.json').read_text())['topology']
assert len(top['nodes'])==17
assert all(n['instance_type']=='t3a.small' and n['az']=='a' for n in top['nodes'].values())
assert sum(n['root_gib']+sum(d['size_gib'] for d in n['data_disks'].values()) for n in top['nodes'].values())==580
print('PASS: Front 경로·WebSocket·허용 CIDR·small 설정·17대/580GiB 선언 검사')
PY
