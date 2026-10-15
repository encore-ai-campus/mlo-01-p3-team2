"""로컬 모의 명령으로 Router 대상·Primary 선택·부분 실행 거부를 확인한다."""
import json
import os
import grp
import pwd
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import jinja2
import yaml

platform = Path(__file__).resolve().parents[1]
ansible = str(Path(sys.executable).with_name("ansible-playbook"))
groups = {
    "mysql": ["mysql-1", "mysql-2", "mysql-3"],
    "game": ["game-server"], "ad": ["ad-server"],
    "spark": ["spark-1", "spark-2", "spark-3"],
    "backend": ["game-server"],
}
hosts = {host: {"ip": f"10.0.0.{index}"} for index, host in enumerate(
    dict.fromkeys(host for members in groups.values() for host in members), 1)}
defaults = yaml.safe_load((platform / "roles/mysql/defaults/main.yml").read_text())
shared = yaml.safe_load((platform / "inventory/group_vars/all/mysql.yml").read_text())
backend = yaml.safe_load((platform / "roles/backend/defaults/main.yml").read_text())
expected = {"game", "ad", "spark", "mysql", "backend"}
for values in (defaults, shared, backend):
    assert set(values["mysql_router_source_groups"]) == expected
assert {"game", "ad", "spark", "mysql"} <= set(defaults["mysql_dev_source_groups"])
site = yaml.safe_load((platform / "site.yml").read_text())
router_play = next(play for play in site if play.get("name") == "MySQL Router")
assert set(router_play["hosts"].split(":")) == expected
assert not (platform / "ad-router.yml").exists()

with tempfile.TemporaryDirectory(prefix="router-scope-") as directory:
    work = Path(directory)
    bindir = work / "bin"
    bindir.mkdir()
    log = work / "calls.jsonl"
    # 시스템 MySQL이나 실제 서버를 사용하지 않는 가짜 CLI다.
    (bindir / "mysql").write_text(
        "#!/usr/bin/env python3\nimport os\nprint(os.environ['MYSQL_PWD'])\n")
    (bindir / "mysqlsh").write_text(
        "#!/usr/bin/env python3\nimport sys,json\n"
        f"with open({str(log)!r},'a') as f: f.write(json.dumps(sys.stdin.read())+'\\n')\n"
        "print('INFRA_ROUTER_DEV_CREATED')\n")
    for file in bindir.iterdir():
        file.chmod(0o755)
    inventory = {
        "all": {"vars": {
            "ansible_connection": "local", "ansible_python_interpreter": sys.executable,
            "ansible_become": False, "proxy_environment": {},
            "mysql_router_source_groups": shared["mysql_router_source_groups"],
        }, "children": {group: {"hosts": {host: hosts[host].copy() for host in members}}
                         for group, members in groups.items()}}
    }
    # 실제 site.yml의 계정 준비 play를 로컬 모의 CLI로 그대로 실행한다.
    play = next(play.copy() for play in site if play.get("name") == "MySQL Router 접속 계정 준비")
    play.update({"gather_facts": False, "vars": {"ansible_facts": {"distribution": "Ubuntu"}},
                 "environment": {"PATH": f"{bindir}:{os.environ['PATH']}"}})
    play_path = work / "prepare.yml"
    play_path.write_text(yaml.safe_dump([play], allow_unicode=True))
    inventory_path = work / "inventory.yml"
    # sudo 없이 검사하도록 사본의 파일 소유권만 현재 사용자로 바꾼다.
    role_copy = work / "roles/mysql"
    shutil.copytree(platform / "roles/mysql", role_copy)
    account_tasks = role_copy / "tasks/router-accounts.yml"
    content = account_tasks.read_text()
    assert "owner: root" in content and "group: root" in content
    account_tasks.write_text(content.replace("owner: root", f"owner: {pwd.getpwuid(os.getuid()).pw_name}")
                             .replace("group: root", f"group: {grp.getgrgid(os.getgid()).gr_name}"))
    env = os.environ.copy()
    env.update({"ANSIBLE_CONFIG": str(platform / "ansible.cfg"),
                "ANSIBLE_ROLES_PATH": str(work / "roles"), "ANSIBLE_NOCOLOR": "1"})

    def execute(roles, limit=None, success=True):
        # 각 시나리오의 임시 해시 파일만 사용해 재실행 분기도 검증한다.
        for index, host in enumerate(groups["mysql"]):
            entry = inventory["all"]["children"]["mysql"]["hosts"][host]
            entry["vault_mysql_passwords"] = {
                "root": roles[index], "failover": "test-failover",
                "router": "test-router", "dev": "test-dev"}
            entry["mysql_router_accounts_stamp"] = str(work / f"{host}.sha256")
        inventory_path.write_text(yaml.safe_dump(inventory))
        args = [ansible, "-i", str(inventory_path), str(play_path), "--tags", "mysql_router"]
        if limit:
            args += ["--limit", limit]
        result = subprocess.run(args, env=env, text=True, capture_output=True)
        assert (result.returncode == 0) == success, result.stdout + result.stderr
        return result

    execute(["SECONDARY", "PRIMARY", "SECONDARY"])
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls) == 2
    primary_ip = hosts["mysql-2"]["ip"]
    assert all(f'host: "{primary_ip}"' in call for call in calls)
    for host in hosts:
        assert hosts[host]["ip"] in calls[0] and hosts[host]["ip"] in calls[1]
    assert calls[1].count("cluster.setupRouterAccount(") == 8
    print("PASS Router target deduplication and actual Primary account preparation")

    execute(["SECONDARY", "PRIMARY", "SECONDARY"])
    assert len(log.read_text().splitlines()) == 3
    print("PASS unchanged metadata accounts are skipped by shared hash")
    for roles in (["SECONDARY"] * 3, ["PRIMARY", "PRIMARY", "SECONDARY"],
                  ["PRIMARY", "", "SECONDARY"]):
        execute(roles, success=False)
        assert len(log.read_text().splitlines()) == 3
    execute(["SECONDARY", "PRIMARY", "SECONDARY"], "mysql-1:mysql-2", success=False)
    assert len(log.read_text().splitlines()) == 3
    print("PASS missing/multiple Primary, offline member and partial MySQL limit rejected")

    # site.yml을 --limit ad로 실행할 때 설치 전에 준비 누락을 거부하는지 확인한다.
    guard = {key: value for key, value in router_play.items() if key != "roles"}
    guard.update({"gather_facts": False, "vars": {"proxy_environment": {}}})
    guard_path = work / "guard.yml"
    guard_path.write_text(yaml.safe_dump([guard], allow_unicode=True))
    result = subprocess.run([ansible, "-i", str(inventory_path), str(guard_path),
                             "--tags", "mysql_router", "--limit", "ad"],
                            env=env, text=True, capture_output=True)
    assert result.returncode != 0 and "--limit" in result.stdout
    print("PASS ad-only limit cannot bypass account preparation")

    # 기존 dev 계정에서는 CREATE·ALTER·GRANT를 실행하지 않아야 한다.
    template_env = jinja2.Environment()
    template_env.filters["to_json"] = json.dumps
    template = template_env.from_string(
        (platform / "roles/mysql/templates/router-dev-access.js.j2").read_text())
    rendered = template.render(**{**defaults, "ip": primary_ip,
        "hostvars": hosts, "mysql_router_hosts": list(hosts),
        "vault_mysql_passwords": {"failover": "test-failover", "dev": "test-dev"}})
    source = work / "dev.js"
    source.write_text(rendered)
    test_js = work / "test.cjs"
    test_js.write_text("""
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
for (const exists of [true, false]) {
  const commands = [];
  const session = {runSql(sql) {
    if (sql.startsWith('SELECT')) return {fetchOne: () => [exists ? 1 : 0]};
    commands.push(sql);
  }};
  vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {
    shell: {connect() {}, getSession: () => session}, print() {}
  });
  assert.equal(commands.filter(sql => sql.startsWith('CREATE USER')).length, exists ? 0 : 8);
  assert.equal(commands.filter(sql => sql.startsWith('ALTER USER')).length, 0);
}
""")
    # 기존 검증기와 같이 WSL에서는 Windows Node도 사용할 수 있다.
    node = shutil.which("node") or shutil.which("node.exe")
    assert node, "Node is required for template checks"
    paths = [str(test_js), str(source)]
    if node.endswith(".exe"):
        paths = [subprocess.check_output(["wslpath", "-w", path], text=True).strip() for path in paths]
    subprocess.run([node, *paths], check=True)
    print("PASS existing dev accounts preserved and missing client accounts created")

    # 실제 backend의 동적 include가 태그 실행에서도 하위 작업을 실행하는지 확인한다.
    backend_tasks = yaml.safe_load((platform / "roles/backend/tasks/main.yml").read_text())
    includes = [task for task in backend_tasks if "ansible.builtin.include_role" in task]
    backend_copy = work / "roles/backend/tasks"
    backend_copy.mkdir(parents=True)
    (backend_copy / "main.yml").write_text(yaml.safe_dump(includes, allow_unicode=True))
    for path, label in [(role_copy / "tasks/repo.yml", "ROUTER_REPO_EXECUTED"),
                        (work / "roles/pkg/tasks/install.yml", "ROUTER_PACKAGES_EXECUTED")]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump([{"name": label, "ansible.builtin.debug": {"msg": label}}]))
    dependency_play = work / "dependencies.yml"
    dependency_play.write_text(yaml.safe_dump([{"hosts": "ad", "gather_facts": False,
        "vars": {"backend_packages": []}, "roles": [{"role": "backend", "tags": ["mysql_router"]}]}]))
    result = subprocess.run([ansible, "-i", str(inventory_path), str(dependency_play),
                             "--tags", "mysql_router"], env=env, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ROUTER_REPO_EXECUTED" in result.stdout and "ROUTER_PACKAGES_EXECUTED" in result.stdout, result.stdout
    print("PASS Router tag executes repository and package dependency tasks")

print("Router integration validation complete; no remote hosts contacted")
