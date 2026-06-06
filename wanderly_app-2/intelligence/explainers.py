"""
The Explainer: a presentation-only layer that turns a deterministic
`ScoredCity` into prose.

Architectural rule, stated once and enforced by structure: **the Explainer
never ranks anything.** It receives an already-scored city and its factor
breakdown and only rephrases it. This is why a tutor asking "why is this
city ranked here?" always gets a real answer from the engine, even if the
LLM is switched off, swapped, or unavailable.

`get_explainer()` reads the dotted path in `settings.WANDERLY_EXPLAINER_BACKEND`,
so choosing a vendor (Gemini, Groq, ...) is a one-line config change, not a
code change. The default `NullExplainer` needs no network and no API key.
"""

from __future__ import annotations

import abc
from importlib import import_module

from django.conf import settings

from .engine import ScoredCity


class Explainer(abc.ABC):
    """Strategy interface for producing a natural-language 'why'."""

    @abc.abstractmethod
    def explain(self, scored: ScoredCity) -> str:
        """Return a short, user-facing justification for the score."""
        raise NotImplementedError


class NullExplainer(Explainer):
    """
    Default explainer: deterministic, offline, zero-dependency.

    It simply surfaces the engine's own factor breakdown as a friendly
    paragraph. Because it derives entirely from the engine, it can never
    contradict the score -- the failure mode we are explicitly avoiding by
    keeping the LLM out of ranking.
    """

    def explain(self, scored: ScoredCity) -> str:
        top = sorted(scored.factors, key=lambda f: f.points, reverse=True)
        if not top:
            return f"{scored.city} scored {scored.score}/100."
        lead = top[0]
        parts = [
            f"{scored.city} scores {scored.score}/100, driven most by "
            f"{lead.name.lower()} ({lead.detail.rstrip('.')})."
        ]
        if len(top) > 1:
            runner = top[1]
            parts.append(f"{runner.name} also helps: {runner.detail.rstrip('.')}.")
        if scored.has_stale_inputs:
            parts.append("Some inputs are aging, so treat this as indicative.")
        return " ".join(parts)


class LLMExplainerBase(Explainer):
    """
    Base for real LLM-backed explainers.

    Subclasses implement `_complete(prompt)` for their vendor. The prompt is
    constructed here from the *deterministic* breakdown, so the model is
    constrained to explaining facts it is given -- it is told explicitly not
    to invent or re-rank. If the call fails, we fall back to NullExplainer
    so the product degrades gracefully rather than breaking.
    """

    SYSTEM_INSTRUCTION = (
        "You are a travel assistant. You will be given a destination's score "
        "and the exact factors that produced it. Explain the result in two or "
        "three friendly sentences. Do NOT change the score, invent facts, or "
        "re-rank anything; only rephrase the breakdown you are given."
    )

    def _build_prompt(self, scored: ScoredCity) -> str:
        return f"{self.SYSTEM_INSTRUCTION}\n\nBreakdown:\n{scored.explain()}"

    @abc.abstractmethod
    def _complete(self, prompt: str) -> str:
        """Call the vendor API and return the completion text."""
        raise NotImplementedError

    def explain(self, scored: ScoredCity) -> str:
        try:
            text = self._complete(self._build_prompt(scored)).strip()
            return text or NullExplainer().explain(scored)
        except Exception:  # noqa: BLE001 -- graceful degradation is the point
            return NullExplainer().explain(scored)


def get_explainer() -> Explainer:
    """
    Instantiate the configured explainer from its dotted path.

    Falls back to NullExplainer if the configured backend cannot be loaded,
    so a misconfiguration never takes the site down.
    """
    path = getattr(
        settings, "WANDERLY_EXPLAINER_BACKEND", "intelligence.explainers.NullExplainer"
    )
    try:
        module_path, _, class_name = path.rpartition(".")
        module = import_module(module_path)
        explainer_cls = getattr(module, class_name)
        return explainer_cls()
    except (ImportError, AttributeError, TypeError):
        return NullExplainer()
