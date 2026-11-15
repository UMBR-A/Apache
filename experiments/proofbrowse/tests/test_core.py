import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from proofbrowse.core import Agent, Policy, Receipts, Refused


class FakeBrowser:
    def __init__(self):
        self.url = "https://example.org/"
        self.text = "Welcome home."
        self.value = None

    async def observe(self):
        return {"url": self.url, "text": self.text}

    async def open(self, url):
        self.url = url
        self.text = "This page says the answer is 42 and nothing else."

    async def click_link(self, text):
        self.url = "https://example.org/facts"
        self.text = "The answer is 42 for this example."

    async def fill(self, selector, value):
        self.value = value
        self.text = "Search has been filled."

    async def click_button(self, text):
        self.text = "Button pressed."


class SequenceModel:
    def __init__(self, *decisions):
        self.decisions = list(decisions)
    async def decide(self, task, observation, history):
        return self.decisions.pop(0)


class ProofBrowseTests(unittest.TestCase):
    def test_domain_scope_and_private_network(self):
        p = Policy(("example.org",))
        self.assertEqual(p.check_url("https://docs.example.org/a"), "docs.example.org")
        for url in ("https://fakeexample.org/", "file:///etc/passwd", "http://localhost/", "http://127.0.0.1/", "http://10.0.0.1/", "http://user:pass@example.org/", "https://example.org.evil.tld/"):
            with self.subTest(url=url), self.assertRaises(Refused):
                p.check_url(url)

    def test_grounded_answer_and_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            model = SequenceModel({"action":"click_link", "text":"Facts", "expected_text":"answer is 42"}, {"action":"finish", "answer":"42", "quote":"The answer is 42"})
            answer = asyncio.run(Agent(FakeBrowser(), model, Policy(("example.org",)), Receipts(path)).run("Find the answer", "https://example.org"))
            self.assertEqual(answer["answer"], "42")
            self.assertTrue(Receipts.verify(path))
            lines = [json.loads(x) for x in path.read_text().splitlines()]
            self.assertEqual(lines[-1]["event"]["status"], "grounded")
            lines[1]["event"]["status"] = "fake"
            path.write_text("\n".join(json.dumps(row) for row in lines) + "\n")
            self.assertFalse(Receipts.verify(path))

    def test_hallucinated_quote_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            model = SequenceModel({"action":"finish", "answer":"Nobody knows", "quote":"This quote was not observed"})
            with self.assertRaises(Refused):
                asyncio.run(Agent(FakeBrowser(), model, Policy(("example.org",), max_steps=1), Receipts(path)).run("Q", "https://example.org"))
            self.assertIn('"status":"refused"', path.read_text())

    def test_write_approval_and_redaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "events.jsonl"
            b = FakeBrowser()
            model = SequenceModel({"action":"fill", "selector":"#search", "value":"private input"})
            with self.assertRaises(Refused):
                asyncio.run(Agent(b, model, Policy(("example.org",), max_steps=1), Receipts(path)).run("Q", "https://example.org"))
            self.assertIsNone(b.value)
            self.assertNotIn("private input", path.read_text())

            other = Path(tmp) / "approved.jsonl"
            async def approve(action, description): return True
            m2 = SequenceModel({"action":"fill", "selector":"#search", "value":"private input"},
                               {"action":"finish", "answer":"filled", "quote":"Search has been filled"})
            asyncio.run(Agent(b, m2, Policy(("example.org",)), Receipts(other), approval=approve).run("Q", "https://example.org"))
            self.assertEqual(b.value, "private input")
            self.assertNotIn("private input", other.read_text())
            self.assertTrue(Receipts.verify(other))


if __name__ == "__main__":
    unittest.main()
