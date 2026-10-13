"""The documented launcher must start one publisher in the serving process."""
import os
import sys
from importlib import import_module
from unittest.mock import patch

from django.test import SimpleTestCase

from .apps import CampusConfig


class PublisherStartupTests(SimpleTestCase):
    def starts_publisher(self, argv, child=False):
        config = CampusConfig("campus", import_module("campus"))
        with patch.object(sys, "argv", argv), \
                patch.dict(os.environ, {"RUN_MAIN": "true" if child else ""}), \
                patch("campus.menu_updater.start_menu_updater"), \
                patch("accounts.session_cleanup.start_session_cleanup"), \
                patch("eventing.publisher.start_outbox_publisher") as start:
            config.ready()
            return start.call_count

    def test_documented_launcher_child_starts_publisher(self):
        self.assertEqual(self.starts_publisher(
            ["C:/3rd-pr-f/backend/run-campus.py", "--port", "9003", "--bind", "127.0.0.1"],
            child=True), 1)

    def test_documented_launcher_without_reload_starts_publisher(self):
        self.assertEqual(self.starts_publisher(["run-campus.py", "--noreload"]), 1)

    def test_reload_parent_does_not_start_publisher(self):
        self.assertEqual(self.starts_publisher(["run-campus.py", "--port", "9003"]), 0)
        self.assertEqual(self.starts_publisher(["manage.py", "runserver"]), 0)

    def test_direct_runserver_still_starts_publisher(self):
        self.assertEqual(self.starts_publisher(["manage.py", "runserver"], child=True), 1)
        self.assertEqual(self.starts_publisher(["manage.py", "runserver", "--noreload"]), 1)

    def test_other_management_commands_do_not_start_publisher(self):
        for command in ["migrate", "check", "test"]:
            with self.subTest(command=command):
                self.assertEqual(self.starts_publisher(["manage.py", command], child=True), 0)
