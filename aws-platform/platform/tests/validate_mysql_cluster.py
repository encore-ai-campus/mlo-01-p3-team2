# Cluster·Router의 로컬 정적/모의 검증이다. 실제 서버에는 접속하지 않는다.
import atexit
# Cluster·Router의 로컬 정적/모의 검증이다. 실제 서버에는 접속하지 않는다.
import atexit
import json
import os
from pathlib import Path
import shutil
import shutil
import subprocess
import sys
import tempfile

import jinja2
import yaml
from ansible.plugins.filter.core import FilterModule
from ansible.plugins.test.core import TestModule

PLATFORM = Path(__file__).resolve().parents[1]
workspace = tempfile.TemporaryDirectory(prefix='mysql-cluster-render-')
atexit.register(workspace.cleanup)
WORK = Path(workspace.name)
defaults = yaml.safe_load((PLATFORM / 'roles/mysql/defaults/main.yml').read_text())
defaults.update(yaml.safe_load((PLATFORM / 'roles/backend/defaults/main.yml').read_text()))
defaults.update(yaml.safe_load((PLATFORM / 'inventory/group_vars/all/mysql.yml').read_text()))
groups = {'mysql': ['mysql-01', 'mysql-02', 'mysql-03'], 'game': ['game-01'], 'spark': ['spark-01'], 'bastion': ['bastion-01']}
ips = ['10.30.20.11', '10.50.20.11', '10.20.20.11', '10.10.20.21', '10.20.20.21', '10.10.0.10']
hostvars = {h: {'ip': ip} for h, ip in zip(sum(groups.values(), []), ips)}
values = dict(defaults, groups=groups, hostvars=hostvars, ip=ips[0], mysql_socket='/var/run/mysqld/mysqld.sock', mysql_server_id=1, mysql_buffer_pool_mb=128, mysql_router_hosts=['game-01', 'spark-01'], vault_mysql_passwords={k: 'ValidP8!/%' for k in ['root', 'dev', 'replication', 'monitor', 'failover', 'router']})
env = jinja2.Environment(undefined=jinja2.StrictUndefined)
env.filters.update(FilterModule().filters())
env.tests.update(TestModule().tests())
rendered = {}
for directory in ['roles/mysql/templates', 'roles/backend/templates']:
    for path in (PLATFORM / directory).glob('*.j2'):
        rendered[path.name] = env.from_string(path.read_text()).render(**values)
for label, allowed in [('cluster-allow.js.j2', True), ('cluster-false-string.js.j2', 'false')]:
    rendered[label] = env.from_string((PLATFORM / 'roles/mysql/templates/cluster.js.j2').read_text()).render(**dict(values, mysql_cluster_allow_clone_data_loss=allowed))
(WORK / 'rendered.json').write_text(json.dumps(rendered))
assert 'RESET BINARY LOGS' not in rendered['accounts.sql.j2']
assert "'dev'@'10.10.20.21'" in rendered['accounts.sql.j2']
assert 'SET sql_log_bin = 0' in rendered['admin-accounts.sql.j2']
assert 'group_replication_' not in '\n'.join(line for line in rendered['infra.cnf.j2'].splitlines() if not line.startswith('#'))
print('All MySQL/Router templates rendered; SQL/config invariants passed', flush=True)
node = shutil.which('node') or shutil.which('node.exe')
if not node:
    sys.exit('Node.js가 필요합니다. WSL PATH에 node 또는 Windows node.exe를 추가하세요.')
node_paths = [str(PLATFORM / 'tests/mysql_cluster.test.cjs'), str(WORK / 'rendered.json')]
if node.endswith('.exe') and sys.platform != 'win32':
    node_paths = [subprocess.check_output(['wslpath', '-w', path], text=True).strip() for path in node_paths]
subprocess.run([node, *node_paths], check=True)

# 실제 Ansible assert 작업만 localhost에서 실행해 잘못된 인벤토리 거부를 확인한다.
main = yaml.safe_load((PLATFORM / 'roles/mysql/tasks/main.yml').read_text())
tasks = [t for t in main if t.get('name') in ['Secret 확인', 'Cluster 인벤토리 확인', '역할 내부 값 계산']]
ansible = str(Path(sys.executable).with_name('ansible-playbook'))
with tempfile.TemporaryDirectory(prefix='mysql-cluster-check-') as directory:
    temp = Path(directory)
    play = [{'hosts': 'mysql', 'gather_facts': False, 'any_errors_fatal': True, 'vars': dict(values, ansible_connection='local', ansible_facts={'memtotal_mb': 512}), 'tasks': tasks}]
    play[0]['vars'].pop('groups')
    play[0]['vars'].pop('hostvars')
    (temp / 'preflight.yml').write_text(yaml.safe_dump(play, allow_unicode=True))
    cases = [
        ('valid-3', ['mysql-01', 'mysql-02', 'mysql-03'], ips[:3], None, True),
        ('reject-2', ['mysql-01', 'mysql-02'], ips[:2], None, False),
        ('reject-duplicate-id', ['mysql-01', 'mysql-1', 'mysql-03'], ips[:3], None, False),
        ('reject-zero-id', ['mysql-00', 'mysql-02', 'mysql-03'], ips[:3], None, False),
        ('reject-duplicate-ip', ['mysql-01', 'mysql-02', 'mysql-03'], [ips[0], ips[0], ips[2]], None, False),
        ('reject-partial-limit', ['mysql-01', 'mysql-02', 'mysql-03'], ips[:3], 'mysql-01', False),
    ]
    for name, hosts, addresses, limit, success in cases:
        inventory = {'all': {'children': {'mysql': {'hosts': {h: {'ip': address} for h, address in zip(hosts, addresses)}}}}}
        (temp / 'inventory.yml').write_text(yaml.safe_dump(inventory))
        args = [ansible, '-i', str(temp / 'inventory.yml'), str(temp / 'preflight.yml')]
        if limit:
            args += ['--limit', limit]
        result = subprocess.run(args, cwd=PLATFORM, capture_output=True, text=True, env=dict(os.environ, ANSIBLE_CONFIG=str(PLATFORM / 'ansible.cfg')))
        if (result.returncode == 0) != success:
            print(result.stdout, result.stderr)
            sys.exit('Unexpected preflight result: ' + name)
        print('PASS Ansible ' + name, flush=True)
    # 실제 재실행 보호 assert에 상태만 주입하여 서비스 시작·파일 쓰기 없이 검사한다.
    guards = [t for t in main if t.get('name') in ['중지된 기존 MySQL 보호', '가입된 Cluster의 설정 포함 변경 제한', '가입된 Cluster의 설정 변경 제한']]
    for name, has_data, socket, metadata, config_changed, include_changed, success in [
        ('fresh-configuration', False, False, False, True, True, True),
        ('existing-healthy', True, True, True, False, False, True),
        ('reject-stopped-existing', True, False, True, False, False, False),
        ('reject-joined-config-drift', True, True, True, True, False, False),
        ('reject-joined-include-drift', True, True, True, False, True, False),
    ]:
        state = dict(ansible_connection='local', ansible_facts={'os_family': 'RedHat'}, mysql_existing_data={'stat': {'exists': has_data}}, mysql_existing_socket={'stat': {'exists': socket}}, mysql_has_metadata=metadata, mysql_config_candidate={'changed': config_changed}, mysql_include_candidate={'changed': include_changed})
        (temp / 'guards.yml').write_text(yaml.safe_dump([{'hosts': 'localhost', 'gather_facts': False, 'vars': state, 'tasks': guards}], allow_unicode=True))
        result = subprocess.run([ansible, '-i', str(temp / 'inventory.yml'), str(temp / 'guards.yml')], cwd=PLATFORM, capture_output=True, text=True, env=dict(os.environ, ANSIBLE_CONFIG=str(PLATFORM / 'ansible.cfg')))
        if (result.returncode == 0) != success:
            print(result.stdout, result.stderr)
            sys.exit('Unexpected guard result: ' + name)
        print('PASS Ansible ' + name, flush=True)
    subprocess.run([ansible, '-i', str(PLATFORM / 'inventory/hosts.example.yml'), str(PLATFORM / 'site.yml'), '--syntax-check'], check=True, cwd=PLATFORM, env=dict(os.environ, ANSIBLE_CONFIG=str(PLATFORM / 'ansible.cfg')))
print('Local validation complete; no remote hosts contacted', flush=True)
