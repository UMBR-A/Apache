"""Route easy decisions locally and uncertain or risky ones to a fallback."""

from __future__ import annotations

import json
from typing import Any, Mapping

from .backends.base import Backend, BackendError


class CascadeBackend:
    """Use a fast primary backend, escalating selected decisions to a fallback.

    The fallback must implement the same typed decision contract. Confidence is only
    a routing hint: known high-impact intents are escalated regardless of confidence.
    The browser loop's confirmation and validation guards remain authoritative.
    """

    name = "cascade"
    RISK_TERMS = (
        "delete", "remove", "purchase", "buy", "checkout", "pay", "transfer",
        "send", "submit", "publish", "post", "cancel subscription", "unsubscribe",
        "change password", "close account", "erase", "refund",
    )

    def __init__(self, primary: Backend, fallback: Backend, *,
                 escalate_below: float = 0.70, escalate_margin: float = 0.10) -> None:
        if not 0 <= escalate_below <= 1:
            raise ValueError("escalate_below must be between 0 and 1")
        if not 0 <= escalate_margin <= 1:
            raise ValueError("escalate_margin must be between 0 and 1")
        self.primary = primary
        self.fallback = fallback
        self.escalate_below = escalate_below
        self.escalate_margin = escalate_margin

    def _reasons(self, state: Any, questions: Mapping[str, Mapping[str, Any]],
                 payload: Mapping[str, Any]) -> list[str]:
        reasons: list[str] = []
        answers = payload.get("answers")
        if not isinstance(answers, Mapping):
            return ["primary returned no answer map"]

        for name, question in questions.items():
            answer = answers.get(name)
            if not isinstance(answer, Mapping):
                return [f"primary omitted {name}"]
            kind = question.get("type")
            if kind == "choice":
                probabilities = answer.get("probabilities")
                if not isinstance(probabilities, Mapping) or not probabilities:
                    return [f"primary returned no probabilities for {name}"]
                try:
                    values = sorted((float(value) for value in probabilities.values()), reverse=True)
                    confidence = float(answer.get("confidence", values[0]))
                except (TypeError, ValueError):
                    return [f"primary returned invalid confidence for {name}"]
                if confidence < self.escalate_below:
                    reasons.append(f"{name} confidence {confidence:.2f} below {self.escalate_below:.2f}")
                if len(values) > 1 and values[0] - values[1] < self.escalate_margin:
                    reasons.append(f"{name} top-choice margin {values[0] - values[1]:.2f} below {self.escalate_margin:.2f}")

        # Task intent is present in the typed question instructions. Escalate if it
        # explicitly involves a consequential action, even when the small model is sure.
        try:
            context = json.dumps({"state": state, "questions": questions}, ensure_ascii=False).casefold()
        except (TypeError, ValueError):
            context = str(state).casefold()
        risky = next((term for term in self.RISK_TERMS if term in context), None)
        if risky:
            reasons.append(f"high-impact intent contains '{risky}'")
        return reasons

    def answer(self, state: Any, questions: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
        primary = self.primary.answer(state, questions)
        reasons = self._reasons(state, questions, primary)
        if not reasons:
            primary.setdefault("backend", getattr(self.primary, "name", "primary"))
            primary["routing"] = {"selected": "primary", "reason": "confidence and risk policy"}
            return primary

        try:
            result = self.fallback.answer(state, questions)
        except Exception as error:
            # Never silently use an uncertain primary answer after escalation was
            # required; the caller's existing fail-open path prevents an action.
            raise BackendError("fallback_failed", f"{type(error).__name__}: {error}") from error
        result.setdefault("backend", getattr(self.fallback, "name", "fallback"))
        result["routing"] = {
            "selected": "fallback",
            "reason": reasons,
            "primary_backend": getattr(self.primary, "name", "primary"),
        }
        result["usage"] = {**(result.get("usage") or {}),
                            "primary_backend": getattr(self.primary, "name", "primary"),
                            "escalation_reasons": reasons}
        return result
