"""Tests for the projector launcher's dev-account config loading."""
import importlib.util
import json
import os
import sys
import tempfile
import unittest

TOOLS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, TOOLS)
_spec = importlib.util.spec_from_file_location(
    "projector_client", os.path.join(TOOLS, "projector-client.py"))
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


class ProjectorConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self._tmp.name, "config.json")

    def tearDown(self):
        self._tmp.cleanup()

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text)

    def test_loads_dev_account(self):
        self.write(json.dumps({"dev_account": {"username": "test", "password": "test123"}}))
        self.assertEqual(pc.load_dev_account(self.path), ("test", "test123"))

    def test_missing_file_is_clear_error_without_secrets(self):
        with self.assertRaises(SystemExit) as cm:
            pc.load_dev_account(self.path)
        self.assertIn("config not found", str(cm.exception))

    def test_invalid_json_is_clear_error_without_contents(self):
        self.write('{"dev_account": {"password": "secret-value"')
        with self.assertRaises(SystemExit) as cm:
            pc.load_dev_account(self.path)
        self.assertIn("not valid JSON", str(cm.exception))
        self.assertNotIn("secret-value", str(cm.exception))

    def test_missing_keys_rejected(self):
        self.write(json.dumps({"dev_account": {"username": "test"}}))
        with self.assertRaises(SystemExit) as cm:
            pc.load_dev_account(self.path)
        self.assertIn("dev_account.username and dev_account.password", str(cm.exception))

    def test_positional_credentials_override_config(self):
        self.write(json.dumps({"dev_account": {"username": "test", "password": "test123"}}))
        argv = ["projector-client.py", "other", "pw"]
        self.assertEqual(pc.credentials(argv, self.path), ("other", "pw"))

    def test_no_credentials_uses_config(self):
        self.write(json.dumps({"dev_account": {"username": "test", "password": "test123"}}))
        argv = ["projector-client.py", "--dry-run"]
        self.assertEqual(pc.credentials(argv, self.path), ("test", "test123"))


class GamePortTest(unittest.TestCase):
    def test_game_port_overrides_sport(self):
        fv = {"sport": "8008", "ip": "127.0.0.1"}
        out = pc.apply_game_port(dict(fv), ["x", "--game-port", "8009"])
        self.assertEqual(out["sport"], "8009")
        self.assertEqual(out["ip"], "127.0.0.1")

    def test_no_game_port_keeps_sport(self):
        fv = {"sport": "8008"}
        self.assertEqual(pc.apply_game_port(dict(fv), ["x"]), fv)


class BuildMovieUrlTest(unittest.TestCase):
    def setUp(self):
        self._orig = (pc.login_legacy, pc.flashvars_of)
        self.seen = []

        def fake_login(user, password):
            self.seen.append((user, password))
            return "<html>"

        pc.login_legacy = fake_login
        pc.flashvars_of = lambda html: {"sport": "8008", "uid": "1"}

    def tearDown(self):
        pc.login_legacy, pc.flashvars_of = self._orig

    def test_builds_url_with_game_port(self):
        url = pc.build_movie_url("test", "test123", argv=["x", "--game-port", "8009"])
        self.assertEqual(self.seen, [("test", "test123")])
        self.assertTrue(url.startswith("http://127.0.0.1/res/Main.swf?"))
        self.assertIn("sport=8009", url)
        self.assertNotIn("test123", url)

    def test_legacy_movie_base_is_honored(self):
        url = pc.build_movie_url("test", "test123", movie_base="http://127.0.0.1:8081/res",
                                 argv=["x"])
        self.assertTrue(url.startswith("http://127.0.0.1:8081/res/Main.swf?"))
        self.assertNotIn("test123", url)

    def test_refusal_raises_system_exit(self):
        def refuse(user, password):
            raise SystemExit("Gamelogin gate refused (bad login?)")

        pc.login_legacy = refuse
        with self.assertRaises(SystemExit):
            pc.build_movie_url("test", "wrong", argv=["x"])


if __name__ == "__main__":
    unittest.main()
