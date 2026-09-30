from __future__ import annotations

import logging
from typing import Any

from backend.agents.base import BaseAgent, is_groq_quota_error
from backend.config.settings import AppConfig
from backend.core.models import (
    DebuggingPlan,
    LearningResource,
    RequestContext,
)

logger = logging.getLogger(__name__)


LIBRARIAN_PROMPT = """You are Turtle, the Librarian agent in Debug2Learn.

Your job is to recommend learning resources that directly help the developer
understand the ACTUAL bug diagnosed by the Solver.

IMPORTANT:

1. Use the Solver's diagnosis as the primary source of truth.
2. Do NOT assume a specific bug pattern.
3. Do NOT recommend resources merely because a keyword appears in the bug report.
4. Resources must explain concepts directly relevant to the diagnosed root cause.
5. Prefer official documentation and highly trusted technical sources.
6. Prefer Python official documentation when the project is Python.
7. Never invent URLs.
8. Do not recommend generic resources when a specific resource is available.
9. Do not recommend resources for an unrelated possible bug.
10. Return only valid JSON.

Return exactly this structure:

{
  "resources": [
    {
      "title": "...",
      "url": "https://...",
      "resource_type": "documentation|tutorial|reference",
      "relevance": "...",
      "concept": "..."
    }
  ]
}

Return 2 to 4 resources.
"""


class LibrarianAgent(BaseAgent):
    """
    Turtle / Librarian.

    Recommends learning resources based on the Solver's diagnosis
    rather than hardcoded bug categories.
    """

    def __init__(self, config: AppConfig):
        super().__init__(
            config,
            system_prompt=LIBRARIAN_PROMPT,
        )

    def find_resources(
        self,
        request_context: RequestContext,
        plan: DebuggingPlan | None = None,
    ) -> list[LearningResource]:
        """
        Find learning resources specifically related to the diagnosed bug.
        """

        if not plan:
            logger.warning("Librarian called without a debugging plan.")
            return self._generic_fallback(request_context)

        root_cause = plan.root_cause_location or plan.bug_location or "unknown"

        hypothesis = plan.hypothesis or ""
        relevant_logic = plan.relevant_logic or ""
        concept = plan.concept or ""

        steps_text = self._format_steps(plan)

        prompt = f"""
Find learning resources for the current debugging problem.

PROJECT DOMAIN:
{request_context.domain}

BUG SYMPTOM:
{request_context.symptom}

RAW BUG REPORT:
{request_context.raw_input}

ERROR MESSAGES:
{self._format_errors(request_context)}

SOLVER DIAGNOSIS
================

Root Cause Location:
{root_cause}

Hypothesis:
{hypothesis}

Relevant Logic:
{relevant_logic}

Concept:
{concept}

Debugging Steps:
{steps_text}

Your task:

1. Identify the exact programming concept the developer needs to understand
   to diagnose or fix THIS bug.

2. Recommend 2 to 4 resources that teach that concept.

3. The resources must directly relate to the Solver diagnosis.

4. Prefer official documentation.

5. For Python projects, prefer:
   - docs.python.org
   - pytest documentation when pytest is directly involved
   - other highly trusted primary documentation when appropriate.

6. Do NOT recommend resources about unrelated concepts.

7. Do NOT infer a different bug from keywords.

8. Do NOT recommend list comprehensions, boolean operators, string methods,
   async programming, dictionaries, or exception handling unless the Solver
   diagnosis actually requires those concepts.

9. Every URL must be a real URL that you are confident exists.

10. Explain briefly why each resource is relevant to THIS diagnosis.

Return only valid JSON.
"""

        if self._model and self.config.groq.api_key:
            try:
                response = self._send_sync(prompt)

                data = self._parse_json_response(response)

                generated = self._parse_resources(data)

                if generated:
                    return generated[:4]

            except Exception as e:
                logger.warning(
                    "Librarian Groq curation failed; using diagnosis fallback: %s",
                    e,
                )

                if is_groq_quota_error(e):
                    logger.warning("Groq quota reached during Librarian curation.")

        return self._diagnosis_fallback(
            request_context=request_context,
            plan=plan,
        )

    def _parse_resources(
        self,
        data: Any,
    ) -> list[LearningResource]:
        """
        Validate resources returned by the LLM.
        """

        if not isinstance(data, dict):
            return []

        raw_resources = data.get("resources", [])

        if not isinstance(raw_resources, list):
            return []

        resources: list[LearningResource] = []

        for item in raw_resources:
            if not isinstance(item, dict):
                continue

            title = str(item.get("title", "")).strip()
            url = str(item.get("url", "")).strip()
            relevance = str(item.get("relevance", "")).strip()

            if not title or not url or not relevance:
                continue

            if not url.startswith(("https://", "http://")):
                continue

            resource_type = str(item.get("resource_type", "documentation")).strip()

            if resource_type not in (
                "documentation",
                "tutorial",
                "reference",
            ):
                resource_type = "documentation"

            concept = str(item.get("concept", "")).strip()

            resources.append(
                LearningResource(
                    title=title,
                    url=url,
                    resource_type=resource_type,
                    relevance=relevance,
                    concept=concept,
                )
            )

        return resources

    def _format_steps(
        self,
        plan: DebuggingPlan,
    ) -> str:
        """
        Convert debugging steps into concise context for Turtle.
        """

        if not plan.steps:
            return "No explicit debugging steps available."

        lines: list[str] = []

        for step in plan.steps[:6]:
            lines.append(
                f"- Step {step.step_number}: {step.title}\n"
                f"  Description: {step.description}\n"
                f"  File: {step.target_file}\n"
                f"  Symbol: {step.target_symbol}"
            )

        return "\n".join(lines)

    def _format_errors(
        self,
        request_context: RequestContext,
    ) -> str:
        """
        Format observed errors without inventing additional information.
        """

        errors = request_context.error_messages

        if not errors:
            return "No explicit error messages provided."

        if isinstance(errors, (list, tuple)):
            return "\n".join(f"- {error!s}" for error in errors[:10])

        return str(errors)

    def _diagnosis_fallback(
        self,
        request_context: RequestContext,
        plan: DebuggingPlan,
    ) -> list[LearningResource]:
        """
        Diagnosis-driven fallback used when Groq is unavailable.

        This intentionally does NOT contain hardcoded bug-specific
        keyword detection.
        """

        concept = plan.concept or plan.hypothesis or "debugging and program behavior"

        domain = (request_context.domain or "").lower()

        resources: list[LearningResource] = []

        if "python" in domain:
            resources.append(
                LearningResource(
                    title="Python Tutorial",
                    url="https://docs.python.org/3/tutorial/",
                    resource_type="tutorial",
                    relevance=(
                        f"Provides official Python documentation for "
                        f"understanding the concepts involved in: {concept}"
                    ),
                    concept=concept,
                )
            )

        elif "pytest" in domain:
            resources.append(
                LearningResource(
                    title="pytest Documentation",
                    url="https://docs.pytest.org/en/stable/",
                    resource_type="documentation",
                    relevance=(
                        f"Official pytest documentation relevant to "
                        f"understanding the diagnosed issue: {concept}"
                    ),
                    concept=concept,
                )
            )

        if not resources:
            resources.append(
                LearningResource(
                    title="Python Tutorial",
                    url="https://docs.python.org/3/tutorial/",
                    resource_type="tutorial",
                    relevance=(
                        f"Official Python documentation for the concepts "
                        f"identified by the Solver: {concept}"
                    ),
                    concept=concept,
                )
            )

        return resources[:4]

    def _generic_fallback(
        self,
        request_context: RequestContext,
    ) -> list[LearningResource]:
        """
        Minimal fallback when no Solver diagnosis exists.
        """

        domain = (request_context.domain or "").lower()

        if "python" in domain:
            return [
                LearningResource(
                    title="Python Tutorial",
                    url="https://docs.python.org/3/tutorial/",
                    resource_type="tutorial",
                    relevance=(
                        "Official Python documentation for learning "
                        "the language and debugging-related concepts."
                    ),
                    concept="Python",
                )
            ]

        return [
            LearningResource(
                title="Python Tutorial",
                url="https://docs.python.org/3/tutorial/",
                resource_type="tutorial",
                relevance=(
                    "Official Python documentation for understanding "
                    "Python programming concepts."
                ),
                concept="Python",
            )
        ]
