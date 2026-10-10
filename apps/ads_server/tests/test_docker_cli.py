"""시험 스크립트의 `docker()` 는 공용 도우미(`scripts/docker_cli.py`) 하나를 쓰고, 스크립트마다 지금의 시간 제한을 넘긴다(계획 4-4k, R5)."""
import importlib.util
import sys
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


class DockerTimeoutTests(SimpleTestCase):
    def load(self, name):
        spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_each_script_keeps_its_timeout_and_a_call_can_override_it(self):
        with mock.patch.object(sys, "path", [str(SCRIPTS), *sys.path]), mock.patch.dict(sys.modules):
            modules = {name: self.load(name) for name in ("mongo_temp_rs", "failure_test", "mysql_cluster")}
            import docker_cli

            with mock.patch.object(docker_cli.subprocess, "run") as run:
                for name, timeout in (("mongo_temp_rs", 120), ("failure_test", 180), ("mysql_cluster", 300)):
                    modules[name].docker("ps", check=False)
                    self.assertEqual(run.call_args.args[0], ["docker", "ps"], name)
                    self.assertEqual((run.call_args.kwargs["timeout"], run.call_args.kwargs["check"]), (timeout, False), name)
                modules["mysql_cluster"].docker("build", "-t", "x", ".", timeout=1800)
                self.assertEqual(run.call_args.kwargs["timeout"], 1800)
                modules["mysql_cluster"].docker("exec", "-i", "n", "cat", input="script")
                self.assertEqual(run.call_args.kwargs["input"], "script")

    def test_only_the_shared_helper_defines_docker(self):
        defined = {p.name for p in SCRIPTS.glob("*.py") if "def docker(" in p.read_text(encoding="utf-8")}
        self.assertEqual(defined, {"docker_cli.py"})
