"""Contract tests for SwiftBrowse's local-first model router."""

from __future__ import annotations

import unittest

from localdecide import Decider, choice
from localdecide.backends.base import BackendError


def answer(selected: str, options: list[str], confidence: float) -> dict:
    rest = (1.0 - confidence) / (len(options) - 1)
    probabilities = {key: confidence if key == selected else rest for key in options}
    return {"answers": {"next": {"type": "choice", "choice": selected,
                                  "confidence": confidence, "probabilities": probabilities}}}


class Backend:
    def __init__(self, name: str, response: dict | Exception):
        self.name, self.response, self.calls = name, response, 0

    def answer(self, state, questions):
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class TestCascade(unittest.TestCase):
    def run_decision(self, state: str, confidence: float):
        primary = Backend("fast-local", answer("open", ["open", "close"], confidence))
        fallback = Backend("strong-api", answer("open", ["open", "close"], 0.96))
        decision = Decider(backend=primary, fallback_backend=fallback, retries=0).decide(
            state, {"next": choice("choose an action", {"open": "Open page", "close": "Close page"})})
        return decision, primary, fallback

    def test_confident_routine_decision_stays_local(self):
        decision, primary, fallback = self.run_decision("Find the help page", 0.92)
        self.assertTrue(decision.ok)
        self.assertEqual(primary.calls, 1)
        self.assertEqual(fallback.calls, 0)
        self.assertEqual(decision.answers.routing["selected"], "primary")

    def test_uncertain_decision_escalates(self):
        decision, primary, fallback = self.run_decision("Find the help page", 0.58)
        self.assertTrue(decision.ok)
        self.assertEqual((primary.calls, fallback.calls), (1, 1))
        self.assertEqual(decision.answers.backend, "strong-api")
        self.assertEqual(decision.answers.routing["selected"], "fallback")

    def test_small_probability_margin_escalates(self):
        primary = Backend("fast-local", {"answers": {"next": {
            "type": "choice", "choice": "open", "confidence": 0.96,
            "probabilities": {"open": 0.45, "close": 0.42, "wait": 0.13}}}})
        fallback = Backend("strong-api", answer("open", ["open", "close", "wait"], 0.80))
        decision = Decider(backend=primary, fallback_backend=fallback, retries=0).decide(
            "Find the help page", {"next": choice("choose", {
                "open": "Open", "close": "Close", "wait": "Wait"})})
        self.assertTrue(decision.ok)
        self.assertEqual(fallback.calls, 1)
        self.assertIn("top-choice margin", " ".join(decision.answers.routing["reason"]))

    def test_risky_intent_escalates_even_when_primary_is_confident(self):
        decision, primary, fallback = self.run_decision("Delete my account", 0.99)
        self.assertTrue(decision.ok)
        self.assertEqual((primary.calls, fallback.calls), (1, 1))
        self.assertIn("high-impact intent", " ".join(decision.answers.routing["reason"]))

    def test_fallback_failure_fails_closed(self):
        primary = Backend("fast-local", answer("open", ["open", "close"], 0.5))
        fallback = Backend("strong-api", RuntimeError("offline"))
        decision = Decider(backend=primary, fallback_backend=fallback, retries=0).decide(
            "Find the help page", {"next": choice("choose", {"open": "Open", "close": "Close"})})
        self.assertFalse(decision.ok)
        self.assertIn("fallback_failed", decision.error)


if __name__ == "__main__":
    unittest.main()
