"""Policy and real-browser tests; websites are replaced with local route fixtures."""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from proofbrowse.core import Agent, Policy, Receipts, Refused
from proofbrowse.network import RouteGate
from proofbrowse.__main__ import PlaywrightBrowser


class StubRequest:
    def __init__(self, url, navigation=False):
        self.url, self.navigation = url, navigation
    def is_navigation_request(self):
        return self.navigation


class StubRoute:
    def __init__(self, url, navigation=False):
        self.request = StubRequest(url, navigation)
        self.aborted = False
        self.allowed = False
    async def abort(self, error_code="failed"):
        self.aborted = True
    async def fallback(self):
        self.allowed = True


class NetworkPolicyTests(unittest.TestCase):
    def test_invalid_allowlist_scopes_rejected_early(self):
        for value in ("", "com", ".example.org", "example.org.", "*.example.org", "127.0.0.1", "EXAMPLE.ORG", "example..org", "domain- .org"):
            with self.subTest(value=value), self.assertRaises(Refused):
                Policy((value,))
        with self.assertRaises(Refused):
            Policy(())
        with self.assertRaises(Refused):
            Policy(("example.org",), max_steps=0)

    def test_bad_ports_rejected(self):
        policy = Policy(("example.org",))
        for url in ("https://example.org:abc/", "https://example.org:99999/"):
            with self.subTest(url=url), self.assertRaises(Refused):
                policy.check_url(url)

    def test_resource_scope_separate_from_navigation(self):
        gate = RouteGate(Policy(("example.org",)), ("assets.cdn.net",))
        async def exercise():
            valid = StubRoute("https://assets.cdn.net/site.css")
            await gate(valid)
            self.assertTrue(valid.allowed)
            remote = StubRoute("https://example.com/track")
            await gate(remote)
            self.assertTrue(remote.aborted)
            internal = StubRoute("http://192.168.1.1/secrets")
            await gate(internal)
            self.assertTrue(internal.aborted)
            navigation = StubRoute("https://assets.cdn.net/redirect", True)
            await gate(navigation)
            self.assertTrue(navigation.aborted)
        asyncio.run(exercise())
        self.assertEqual(gate.allowed, 1)
        self.assertEqual(gate.blocked, 3)


class ScriptedModel:
    def __init__(self):
        self.decisions = [
            {"action": "click_link", "text": "Facts", "expected_text": "The answer is 42"},
            {"action": "finish", "answer": "42", "quote": "The answer is 42"},
        ]
    async def decide(self, task, observation, history):
        return self.decisions.pop(0)


class FixturePage:
    """Real Chromium DOM with deterministic fixture-backed navigation.

    The execution environment can forbid all network navigation, even with
    Playwright route.fulfill; this exercises real selectors and DOM extraction
    without making a claim about an end-to-end network browser run.
    """
    def __init__(self, page):
        self.page = page
        self.url = "about:blank"

    async def goto(self, url, **kwargs):
        self.url = url
        html = ("<h1>Research demo</h1><a href='/facts'>Facts</a>"
                if url.endswith("/start") else "<h1>The answer is 42</h1>")
        await self.page.set_content("<html><body>" + html + "</body></html>")

    def get_by_role(self, *args, **kwargs):
        return self.page.get_by_role(*args, **kwargs)

    def locator(self, *args, **kwargs):
        return self.page.locator(*args, **kwargs)

    async def evaluate(self, *args, **kwargs):
        return await self.page.evaluate(*args, **kwargs)


class ChromiumSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_navigation_and_evidence_using_real_chromium_dom(self):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.skipTest("Playwright is not installed")
        executable = (os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
                      or shutil.which("chromium") or shutil.which("google-chrome"))
        if not executable:
            self.skipTest("A local Chromium binary is not installed")
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True, executable_path=executable,
                                                args=["--no-sandbox"])
            try:
                page = await browser.new_page()
                fixture_page = FixturePage(page)
                policy = Policy(("example.org",))
                with tempfile.TemporaryDirectory() as folder:
                    receipts_path = Path(folder) / "receipts.jsonl"
                    result = await Agent(PlaywrightBrowser(fixture_page, policy), ScriptedModel(),
                                         policy, Receipts(receipts_path)).run(
                        "Read the answer from Facts", "https://demo.example.org/start")
                    self.assertEqual(result["answer"], "42")
                    self.assertEqual(result["source"], "https://demo.example.org/facts")
                    self.assertTrue(Receipts.verify(receipts_path))
                    statuses = [json.loads(line)["event"]["status"] for line in receipts_path.read_text().splitlines()]
                    self.assertEqual(statuses, ["start", "observed", "grounded"])
            finally:
                await browser.close()


if __name__ == "__main__":
    unittest.main()
