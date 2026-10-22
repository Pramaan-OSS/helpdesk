"""First-run configuration checks use only temporary local files."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_pramaan_stubs import boundary

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("local_config", ROOT / "scripts/local-config.py")
config = importlib.util.module_from_spec(spec); spec.loader.exec_module(config)


class LocalStartTests(unittest.TestCase):
    def test_generated_credentials_are_private_stable_and_never_printed(self):
        runtime = ROOT / ".runtime"; runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as directory:
            root = Path(directory)
            (root / ".env.example").write_text("PRAMAAN_API_KEY=fixture-local-only\n")
            output = io.StringIO()
            with contextlib.redirect_stdout(output): config.configure(root)
            original = (root / ".env").read_text()
            values = dict(line.split("=", 1) for line in original.splitlines())
            self.assertEqual(values["PRAMAAN_API_KEY"], "fixture-local-only")
            for key in ["LOCAL_DB_PASSWORD", "HELPDESK_ADMIN_PASSWORD", "HELPDESK_ENCRYPTION_KEY"]:
                self.assertGreaterEqual(len(values[key]), 32)
                self.assertNotIn(values[key], output.getvalue())
            self.assertEqual((root / ".env").stat().st_mode & 0o777, 0o600)
            self.assertEqual((root / ".runtime/local-admin-password").stat().st_mode & 0o777, 0o600)
            with contextlib.redirect_stdout(output): config.configure(root)
            self.assertEqual((root / ".env").read_text(), original)
            with contextlib.redirect_stdout(output): config.configure(root, "18009")
            self.assertIn("HELPDESK_LOCAL_PORT=18009", (root / ".env").read_text())
            self.assertIn(values["HELPDESK_ADMIN_PASSWORD"], (root / ".env").read_text())

    def test_explicit_fixture_mode_has_no_network_fallback(self):
        with patch.dict(boundary.os.environ, {"PRAMAAN_FAKE": "1"}), patch.object(boundary, "build_opener") as network:
            client = boundary.PramaanClient(api_key="fixture-local-only")
            self.assertEqual(client.call("companies.enrich", {"domain": "example.test"})["name"], "Local fixture company")
            with self.assertRaises(boundary.PramaanError): client.call("web.read", {"url": "https://example.test"})
            network.assert_not_called()
