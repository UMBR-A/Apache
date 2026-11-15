import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmark.run import load_tasks, evaluate, score, summarize


class BenchmarkTests(unittest.TestCase):
    def test_task_fixture_validation(self):
        tasks = load_tasks()
        self.assertGreaterEqual(len(tasks), 3)
        self.assertEqual(len(tasks), len({t["id"] for t in tasks}))

    def test_scoring_is_strict(self):
        self.assertTrue(score("Example Domain", "Example Domain"))
        self.assertFalse(score("Example Domain", "There is an Example Domain on this page"))
        self.assertFalse(score("42", "142"))

    def test_dry_run_is_not_a_benchmark_result(self):
        args = SimpleNamespace(agent="both", dry_run=True)
        tasks = load_tasks()
        rows = asyncio.run(evaluate(tasks, args))
        self.assertEqual(len(rows), len(tasks) * 2)
        self.assertTrue(all(x["status"] == "not_run" and x["correct"] is None for x in rows))
        summary = summarize(rows)
        self.assertEqual(summary["browser-use"]["completed"], 0)
        self.assertEqual(summary["proofbrowse"]["correct"], 0)


if __name__ == "__main__":
    unittest.main()
