from __future__ import annotations

import logging
from typing import Any

from debug2learn.config.settings import AppConfig
from debug2learn.core.models import DebuggingPlan, LearningResource, RequestContext

logger = logging.getLogger(__name__)


class LibrarianAgent:
    """
    📚 Librarian — Recommends curated learning materials targeted to the diagnosed bug.
    """

    def __init__(self, config: AppConfig):
        self.config = config

    def find_resources(
        self,
        request_context: RequestContext,
        plan: DebuggingPlan | None = None,
    ) -> list[LearningResource]:
        """Find relevant documentation and tutorials based on the diagnosed issue."""
        resources: list[LearningResource] = []
        
        # Combine concept signals from plan and request
        concept_text = " ".join([
            plan.concept if plan else "",
            plan.hypothesis if plan else "",
            plan.relevant_logic if plan else "",
            request_context.domain,
            request_context.symptom,
            request_context.raw_input,
        ]).lower()

        is_logic_or_filtering = any(
            k in concept_text
            for k in ("filter", "comprehension", "boolean", "condition", "[x]", "count", "pending", "not ")
        )
        is_type_issue = any(k in concept_text for k in ("typeerror", "type", "concatenate", "operand"))
        is_dict_or_index = any(k in concept_text for k in ("keyerror", "indexerror", "out of range", "mapping"))
        is_async_issue = any(k in concept_text for k in ("async", "await", "coroutine", "event loop"))

        # 1. Logic / Filtering / List Comprehension Resources
        if is_logic_or_filtering:
            resources.append(LearningResource(
                title="Python Tutorial: List Comprehensions with Conditional Filtering",
                url="https://docs.python.org/3/tutorial/datastructures.html#list-comprehensions",
                resource_type="documentation",
                relevance="Explains how to use the 'if' clause to selectively filter items in a list comprehension",
                concept="List Comprehensions & Filtering",
            ))
            resources.append(LearningResource(
                title="Python Standard Library: Boolean Operations (`not`, `and`, `or`)",
                url="https://docs.python.org/3/library/stdtypes.html#boolean-operations-and-or-not",
                resource_type="documentation",
                relevance="How to use the 'not' operator to invert a condition and filter out matching items",
                concept="Boolean Negation (`not`)",
            ))
            if "startswith" in concept_text or "[x]" in concept_text:
                resources.append(LearningResource(
                    title="Python String Methods: str.startswith()",
                    url="https://docs.python.org/3/library/stdtypes.html#str.startswith",
                    resource_type="documentation",
                    relevance="Checking prefixes and using negation to identify items without the prefix",
                    concept="String Pattern Matching",
                ))

        # 2. Type System Resources
        if is_type_issue:
            resources.append(LearningResource(
                title="Python Type Hierarchy & Common TypeErrors",
                url="https://docs.python.org/3/library/stdtypes.html",
                resource_type="documentation",
                relevance="Explains how Python evaluates operations across different types",
                concept="Type Systems",
            ))

        # 3. Data Structure Access Resources
        if is_dict_or_index:
            resources.append(LearningResource(
                title="Python dict.get() & Safe Sequence Indexing",
                url="https://docs.python.org/3/tutorial/datastructures.html#dictionaries",
                resource_type="documentation",
                relevance="Preventing KeyError and IndexError when accessing dynamic collections",
                concept="Data Structure Safety",
            ))

        # 4. Async Resources
        if is_async_issue:
            resources.append(LearningResource(
                title="Python Async/Await Primer",
                url="https://docs.python.org/3/library/asyncio-task.html",
                resource_type="tutorial",
                relevance="Explains coroutine execution and common await omissions",
                concept="Asynchronous Execution",
            ))

        # 5. ONLY add generic exception tutorial if there is a real unhandled exception and not just a logic error
        if request_context.error_messages and not is_logic_or_filtering:
            resources.append(LearningResource(
                title="Python Tutorial: Errors and Exceptions",
                url="https://docs.python.org/3/tutorial/errors.html",
                resource_type="tutorial",
                relevance="How Python traces runtime errors and proper exception handling techniques",
                concept="Exception Handling",
            ))

        # If nothing matched, provide general Python documentation
        if not resources:
            resources.append(LearningResource(
                title="Official Python Tutorial: Control Flow and Expressions",
                url="https://docs.python.org/3/tutorial/controlflow.html",
                resource_type="tutorial",
                relevance="Covers if statements, conditional expressions, and looping patterns",
                concept="Control Flow",
            ))

        return resources
