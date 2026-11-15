"""Opt-in, same-task/same-local-model browser-agent evaluation.

No model requests or websites are fetched in --dry-run mode. Real evaluation
needs a running Ollama server, Chromium and optional Browser Use dependencies.
Each result is marked success, failure, skipped or not_run; never fabricated.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path
from urllib.parse import urlsplit

from proofbrowse.core import Agent, Policy, Receipts, normalized

TASKS = Path(__file__).with_name("tasks.json")


def load_tasks(path: Path = TASKS) -> list[dict]:
    tasks = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("Expected a nonempty JSON task list")
    seen = set()
    for task in tasks:
        for key in ("id", "start_url", "task", "expected", "allowed_domains"):
            if not task.get(key):
                raise ValueError(f"Missing {key} in benchmark task")
        if task["id"] in seen:
            raise ValueError("Duplicate benchmark task id")
        seen.add(task["id"])
        Policy(tuple(task["allowed_domains"])).check_url(task["start_url"])
    return tasks


def score(expected: str, answer: str) -> bool:
    """Strict extractive scoring, rather than trusting a model's success claim."""
    return normalized(expected).strip(" .") == normalized(answer).strip(" .")


async def run_proofbrowse(task: dict, args: argparse.Namespace) -> dict:
    from playwright.async_api import async_playwright
    from proofbrowse.__main__ import Ollama, PlaywrightBrowser

    policy = Policy(tuple(task["allowed_domains"]), args.max_steps)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(accept_downloads=False)

        async def guard(route):
            if route.request.is_navigation_request():
                try:
                    policy.check_url(route.request.url)
                except ValueError:
                    await route.abort()
                    return
            await route.continue_()

        await context.route("**/*", guard)
        page = await context.new_page()
        receipt_file = Path(args.output_dir) / (task["id"] + "-receipts.jsonl")
        if receipt_file.exists():
            receipt_file.unlink()  # Each benchmark run gets an independent receipt chain.
        try:
            result = await Agent(
                PlaywrightBrowser(page, policy), Ollama(args.model, args.ollama_url),
                policy, Receipts(receipt_file)
            ).run(task["task"], task["start_url"])
            return {"answer": result["answer"], "evidence": result["quote"],
                    "receipt_valid": Receipts.verify(receipt_file)}
        finally:
            await browser.close()


async def run_browser_use(task: dict, args: argparse.Namespace) -> dict:
    # Both products use the same installed local model. The framework prompts,
    # browsing implementation and number of internal model calls can still differ.
    from browser_use import Agent as BrowserUseAgent, Browser, ChatOpenAI

    llm = ChatOpenAI(args.model, base_url=args.browser_use_base_url, api_key="ollama")
    browser = Browser("chromium", allowed_domains=task["allowed_domains"])
    prompt = (f"Start at {task['start_url']}. {task['task']} "
              "Only browse these approved websites: " + ", ".join(task["allowed_domains"]) +
              ". Read-only: do not fill forms, sign in, download, or submit anything. "
              "Return only the exact requested answer without commentary.")
    result = await BrowserUseAgent(prompt, llm=llm, browser=browser).run()
    answer = result.final_result()
    return {"answer": str(answer or ""), "evidence": None, "receipt_valid": None}


async def evaluate(tasks: list[dict], args: argparse.Namespace) -> list[dict]:
    runners = {"proofbrowse": run_proofbrowse, "browser-use": run_browser_use}
    agents = list(runners) if args.agent == "both" else [args.agent]
    records = []
    for task in tasks:
        for name in agents:
            item = {"task": task["id"], "agent": name, "status": "not_run",
                    "correct": None, "elapsed_seconds": None, "receipt_valid": None}
            if args.dry_run:
                records.append(item)
                continue
            start = time.perf_counter()
            try:
                result = await asyncio.wait_for(runners[name](task, args), timeout=args.timeout)
                item.update(status="completed", correct=score(task["expected"], result["answer"]),
                            receipt_valid=result["receipt_valid"], answer=result["answer"][:500])
            except (ImportError, ModuleNotFoundError) as e:
                item.update(status="skipped", error=type(e).__name__ + ": " + str(e)[:180])
            except Exception as e:
                # Avoid emitting exception messages: they can contain untrusted page content.
                item.update(status="failed", error_type=type(e).__name__)
            item["elapsed_seconds"] = round(time.perf_counter() - start, 3)
            records.append(item)
    return records


def summarize(records: list[dict]) -> dict:
    result = {}
    for agent in sorted({r["agent"] for r in records}):
        rows = [r for r in records if r["agent"] == agent]
        completed = [r for r in rows if r["status"] == "completed"]
        times = [r["elapsed_seconds"] for r in completed if r["elapsed_seconds"] is not None]
        result[agent] = {"tasks_total": len(rows), "completed": len(completed),
                         "correct": sum(r["correct"] is True for r in completed),
                         "mean_seconds": round(statistics.mean(times), 3) if times else None,
                         "scoring_note": "Only completed tasks count; no superiority claim without full runs"}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Side-by-side public-web browser-agent benchmark")
    parser.add_argument("--agent", choices=["both", "proofbrowse", "browser-use"], default="both")
    parser.add_argument("--model", default="llama3.2:3b")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434/api/chat")
    parser.add_argument("--browser-use-base-url", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--tasks", type=Path, default=TASKS)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-results"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.timeout <= 0 or args.max_steps < 1:
        parser.error("--timeout and --max-steps must be positive")
    tasks = load_tasks(args.tasks)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows = asyncio.run(evaluate(tasks, args))
    report = {"configuration": {"model": args.model, "agent": args.agent,
               "dry_run": args.dry_run, "max_steps": args.max_steps,
               "task_count": len(tasks), "model_consistency": "same Ollama checkpoint"},
              "summary": summarize(rows), "results": rows}
    path = args.output_dir / "report.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    print("Detailed report:", path)
    return 0 if args.dry_run or all(r["status"] == "completed" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
