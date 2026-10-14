"""`tests/tools/cluster_check.sh` 의 기동 실패 처리(검토 P2-5): 클러스터를 띄우지 못하면 후속 시험도, 이전 ID 에 대한 정리 호출도 없이 비정상 종료한다.

실제 Docker 없이 셸 스텁으로 확인한다: 스크립트를 임시 폴더로 복사하고 `PYTHON`·`check.sh` 를 호출 기록만 남기는 스텁으로 바꾼다.
"""
import os
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, tag

from tests.support.helpers import BASE_DIR
from tests.support.cases import Cases

SCRIPT = BASE_DIR / "tests" / "tools" / "cluster_check.sh"


def executable(path, text):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@tag("security")
class ClusterCheckScriptTests(Cases, SimpleTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        (self.tmp / "tests" / "tools").mkdir(parents=True)
        shutil.copy(SCRIPT, self.tmp / "tests" / "tools" / "cluster_check.sh")
        self.log = self.tmp / "calls.log"
        # 스텁 파이썬: 호출 인자를 기록하고, `mysql_cluster.py start` 의 동작은 STUB_START 로 정한다
        executable(self.tmp / "fakepython", f"""#!/bin/bash
echo "python $*" >> "{self.log}"
case "$*" in
  *"mysql_cluster.py start"*)
    case "$STUB_START" in
      fail-silent) exit 7 ;;
      fail-noisy) echo "export MYSQL_CLUSTER_ID=stale00 DB_PORT=1"; exit 7 ;;
      empty) exit 0 ;;
      ok) echo "export MYSQL_CLUSTER_ID=fresh01 DB_HOST=127.0.0.1 DB_PORT=4242 DB_USER=dev DB_PASSWORD=x"; exit 0 ;;
    esac ;;
esac
exit 0
""")
        executable(self.tmp / "tests" / "tools" / "check.sh", f'#!/bin/bash\necho "check.sh ran" >> "{self.log}"\nexit "${{STUB_CHECK_EXIT:-0}}"\n')

    def run_script(self, start, *args, check_exit="0", env_extra=None):
        env = {**os.environ, "PYTHON": str(self.tmp / "fakepython"), "STUB_START": start, "STUB_CHECK_EXIT": check_exit, **(env_extra or {})}
        result = subprocess.run(["bash", str(self.tmp / "tests" / "tools" / "cluster_check.sh"), *args], capture_output=True, text=True, env=env, cwd=self.tmp)
        calls = self.log.read_text() if self.log.exists() else ""
        return result, calls

    def case_a_silent_start_failure_stops_everything_and_never_touches_an_old_cluster(self):
        """검토 재현: 기동 명령이 출력 없이 종료 코드 7 로 실패하고 환경에 이전 MYSQL_CLUSTER_ID 가 남아 있어도 — 후속 시험도 정리 호출도 없다."""
        result, calls = self.run_script("fail-silent", env_extra={"MYSQL_CLUSTER_ID": "oldid99", "DB_PORT": "9"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("check.sh ran", calls)
        self.assertNotIn("load_test", calls)
        self.assertNotIn("stop", calls)
        self.assertNotIn("oldid99", calls)
        self.assertNotIn("모두 통과", result.stdout)

    def case_a_failed_start_that_printed_something_is_still_a_failure(self):
        result, calls = self.run_script("fail-noisy")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("check.sh ran", calls)
        self.assertNotIn("stale00", calls)  # 실패한 기동이 출력한 ID 로도 정리하지 않는다(만들어지지 않은 클러스터)

    def case_a_start_that_prints_no_cluster_id_is_a_failure(self):
        result, calls = self.run_script("empty", env_extra={"MYSQL_CLUSTER_ID": "oldid99"})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("check.sh ran", calls)
        self.assertNotIn("stop", calls)

    def case_the_success_path_runs_the_checks_and_stops_only_this_runs_cluster(self):
        result, calls = self.run_script("ok", env_extra={"MYSQL_CLUSTER_ID": "oldid99"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("check.sh ran", calls)
        self.assertIn("load_test.py", calls)
        self.assertIn("mysql_cluster.py stop fresh01", calls)
        self.assertNotIn("oldid99", calls)
        self.assertIn("클러스터 점검 모두 통과", result.stdout)

    def case_a_failing_check_makes_the_script_fail_but_the_cluster_is_still_stopped(self):
        result, calls = self.run_script("ok", check_exit="1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("mysql_cluster.py stop fresh01", calls)
        self.assertIn("check.sh", result.stdout)

    def case_failure_scenarios_are_added_only_with_the_flag(self):
        _, calls = self.run_script("ok")
        self.assertNotIn("failure_test", calls)
        _, calls = self.run_script("ok", "--failure")
        self.assertIn("failure_test.py --mysql cluster", calls)

    def test_cluster_check_script(self):
        self.run_cases()
