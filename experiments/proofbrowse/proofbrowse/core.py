"""Audit-first, constrained AI browser runner. No credentials are written to receipts."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import urlsplit


class Refused(ValueError):
    """A policy or evidence check blocked an action."""


def canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalized(text: str) -> str:
    return " ".join(text.split()).casefold()


@dataclass(frozen=True)
class Policy:
    allowed_domains: tuple[str, ...]
    max_steps: int = 12

    def check_url(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise Refused("Only HTTP(S) websites are permitted")
        if parts.username or parts.password:
            raise Refused("URLs containing credentials are blocked")
        host = parts.hostname.rstrip(".").lower()
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
                raise Refused("Local hosts are blocked")
            if not re.fullmatch(r"[a-z0-9.-]+", host):
                raise Refused("Invalid hostname")
            if any(not label or label.startswith("-") or label.endswith("-") for label in host.split(".")):
                raise Refused("Invalid hostname")
        else:
            if not ip.is_global:
                raise Refused("Private, loopback, and reserved IP addresses are blocked")
        if not any(host == base or host.endswith("." + base) for base in self.allowed_domains):
            raise Refused(f"Domain not permitted: {host}")
        return host


class Receipts:
    def __init__(self, destination: str | Path):
        self.destination = Path(destination)
        self.previous = "0" * 64
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        if self.destination.exists() and self.destination.stat().st_size:
            if not self.verify(self.destination):
                raise Refused("Existing receipt file is corrupt")
            for line in self.destination.read_text(encoding="utf-8").splitlines():
                self.previous = json.loads(line)["hash"]

    def write(self, event: dict[str, Any]) -> None:
        data = {"event": event, "previous": self.previous}
        digest = sha(canonical(data))
        with self.destination.open("a", encoding="utf-8") as f:
            f.write(canonical({**data, "hash": digest}) + "\n")
        self.previous = digest

    @staticmethod
    def verify(destination: str | Path) -> bool:
        previous = "0" * 64
        try:
            lines = Path(destination).read_text(encoding="utf-8").splitlines()
            if not lines:
                return False
            for line in lines:
                row = json.loads(line)
                if set(row) != {"event", "previous", "hash"} or row["previous"] != previous:
                    return False
                if sha(canonical({"event": row["event"], "previous": previous})) != row["hash"]:
                    return False
                previous = row["hash"]
            return True
        except (OSError, ValueError, TypeError, KeyError):
            return False


class Browser(Protocol):
    async def observe(self) -> dict[str, str]: ...
    async def open(self, url: str) -> None: ...
    async def click_link(self, text: str) -> None: ...
    async def fill(self, selector: str, value: str) -> None: ...
    async def click_button(self, text: str) -> None: ...


class Model(Protocol):
    async def decide(self, task: str, observation: dict[str, str], history: list[dict[str, str]]) -> dict[str, str]: ...


Approval = Callable[[str, str], Awaitable[bool]]


class Agent:
    def __init__(self, browser: Browser, model: Model, policy: Policy, receipts: Receipts,
                 approval: Approval | None = None):
        self.browser, self.model, self.policy, self.receipts = browser, model, policy, receipts
        self.approval = approval

    async def run(self, task: str, start_url: str) -> dict[str, str]:
        self.policy.check_url(start_url)
        await self.browser.open(start_url)
        history: list[dict[str, str]] = []
        self.receipts.write({"step": 0, "status": "start", "url": start_url, "task_sha256": sha(task)})
        for step in range(1, self.policy.max_steps + 1):
            before = await self.browser.observe()
            self.policy.check_url(before["url"])
            proposed = await self.model.decide(task, before, history)
            action = str(proposed.get("action", ""))
            if action == "finish":
                quote = str(proposed.get("quote", "")).strip()
                if len(quote) < 8 or normalized(quote) not in normalized(before.get("text", "")):
                    self.receipts.write({"step": step, "action": action, "status": "refused", "reason": "quote not found in observed page"})
                    history.append({"action": action, "status": "refused: quote not found"})
                    continue
                result = {"answer": str(proposed.get("answer", "")), "source": before["url"], "quote": quote}
                self.receipts.write({"step": step, "action": action, "status": "grounded", "source": before["url"], "quote": quote})
                return result
            try:
                if action == "open":
                    target = str(proposed.get("url", ""))
                    self.policy.check_url(target)
                    await self.browser.open(target)
                elif action == "click_link":
                    await self.browser.click_link(str(proposed.get("text", "")))
                elif action in {"fill", "click_button"}:
                    description = (str(proposed.get("selector", "")) if action == "fill" else str(proposed.get("text", "")))[:160]
                    if not self.approval or not await self.approval(action, description):
                        raise Refused("Explicit human approval required")
                    if action == "fill":
                        await self.browser.fill(str(proposed.get("selector", "")), str(proposed.get("value", "")))
                    else:
                        await self.browser.click_button(str(proposed.get("text", "")))
                else:
                    raise Refused("Unsupported action")
                after = await self.browser.observe()
                self.policy.check_url(after["url"])
                expected = str(proposed.get("expected_text", "")).strip()
                has_evidence = (normalized(expected) in normalized(after.get("text", "")) if expected else
                                after.get("text") != before.get("text") or after["url"] != before["url"])
                status = "observed" if has_evidence else "unverified"
                event: dict[str, Any] = {"step": step, "action": action, "status": status,
                    "before_url": before["url"], "after_url": after["url"],
                    "before_sha256": sha(before.get("text", "")), "after_sha256": sha(after.get("text", ""))}
                if action == "fill":
                    event["value_sha256"] = sha(str(proposed.get("value", "")))
                    event["value_length"] = len(str(proposed.get("value", "")))
                if expected:
                    event["expected_text_sha256"] = sha(expected)
            except Exception as exc:
                if not isinstance(exc, Refused):
                    # Browser errors may include site content, which must never enter receipts.
                    reason = type(exc).__name__
                else:
                    reason = str(exc)
                status = "refused" if isinstance(exc, Refused) else "failed"
                event = {"step": step, "action": action, "status": status, "reason": reason}
            self.receipts.write(event)
            history.append({"action": action, "status": status})
        raise Refused("Step limit reached without a page-grounded answer")
