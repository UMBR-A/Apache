"""GlassBox receipt tests: additive MCP response contract and plugin metadata."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from localdecide.mcp_server import _Session, _rank_options

ROOT = Path(__file__).resolve().parents[1]


class TestGlassBoxRanking(unittest.TestCase):
    def test_rank_options_is_stable_and_labeled(self):
        ranked = _rank_options({"2": 0.7, "1": 0.7, "3": 0.1}, {"1": "Search", "2": "Home"})
        self.assertEqual([item["option"] for item in ranked], ["1", "2", "3"])
        self.assertEqual(ranked[0]["label"], "Search")
        self.assertEqual(ranked[0]["probability"], 0.7)
        self.assertEqual(len(_rank_options({str(i): 1 / 21 for i in range(21)})), 3)

    def test_page_decide_includes_additive_receipt(self):
        class Answers:
            raw = {
                "operation": {"choice": "CLICK", "probabilities": {"CLICK": 0.8, "WAIT": 0.15, "DONE": 0.05}, "confidence": 0.8},
                "click_target": {"choice": "1", "probabilities": {"1": 0.75, "2": 0.25}, "confidence": 0.75},
            }
            backend = "fake"
            routing = {"reason": "local"}

            def choice(self, name):
                return self.raw[name]["choice"]

            def confidence(self, name):
                return self.raw[name]["confidence"]

            def probabilities(self, name):
                return self.raw[name]["probabilities"]

        class StubDecider:
            def decide(self, state, questions):
                return type("Decision", (), {"ok": True, "answers": Answers(), "latency_ms": 4})()

        session = _Session()
        session._decider = StubDecider()
        result = session._call_tool({
            "name": "page_decide",
            "arguments": {
                "goal": "Open Search",
                "observation": {"actions": [
                    {"kind": "click", "label": "Search", "role": "link"},
                    {"kind": "click", "label": "Home", "role": "link"},
                ]},
            },
        })
        payload = json.loads(result["content"][0]["text"])
        self.assertEqual(payload["operation"], "CLICK")
        self.assertEqual(payload["receipt"]["operation"]["selected"], "CLICK")
        self.assertEqual(payload["receipt"]["target"]["label"], "Search")
        self.assertEqual(payload["receipt"]["target"]["alternatives"][1]["label"], "Home")
        self.assertEqual(payload["receipt"]["offered_elements"], 2)


class TestGlassBoxManifests(unittest.TestCase):
    def test_plugin_manifests_are_valid_json_and_have_local_server(self):
        paths = [
            ".claude-plugin/marketplace.json",
            ".agents/plugins/marketplace.json",
            ".agents/plugins/glassbox/plugin.json",
            ".agents/plugins/glassbox/mcp.json",
            ".agents/plugins/glassbox/.claude-plugin/plugin.json",
            ".agents/plugins/glassbox/.mcp.json",
        ]
        manifests = {
            path: json.loads((ROOT / path).read_text(encoding="utf-8"))
            for path in paths
        }
        self.assertEqual(manifests[".claude-plugin/marketplace.json"]["plugins"][0]["name"], "glassbox")
        self.assertEqual(manifests[".agents/plugins/marketplace.json"]["plugins"][0]["name"], "glassbox")
        self.assertEqual(
            manifests[".agents/plugins/glassbox/mcp.json"]["mcpServers"]["glassbox"]["command"],
            "uvx",
        )
        self.assertEqual(
            manifests[".agents/plugins/glassbox/.mcp.json"]["mcpServers"]["glassbox"]["command"],
            "uvx",
        )


if __name__ == "__main__":
    unittest.main()
