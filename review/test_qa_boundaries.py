"""Public startup and retired connection paths stay self-contained."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class QABoundaryTests(unittest.TestCase):
    def test_login_has_no_external_authorization_request(self):
        login = (ROOT / "helpdesk/www/login.html").read_text()
        self.assertNotIn("helpdesk.api.social.start", login)
        self.assertNotIn("helpdesk.api.social.status", login)
        self.assertIn("/api/method/login", login)

    def test_documentation_links_have_a_real_local_route(self):
        router = (ROOT / "desk/src/router/index.ts").read_text()
        self.assertIn('path: "/guide"', router)
        for source in (ROOT / "desk/src").rglob("*.vue"):
            self.assertNotIn("/helpdesk/knowledge-base", source.read_text(), str(source.relative_to(ROOT)))
