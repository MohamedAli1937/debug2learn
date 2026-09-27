from fastapi import applications
from __future__ import annotations

import logging
from typing import Any

from debug2learn.agents.base import BaseAgent, is_groq_quota_error
from debug2learn.config.settings import AppConfig
from debug2learn.core.models import (
    DebuggingPlan,
    DebuggingStep,
    Hint,
    HintLevel,
    RequestContext,
    SessionState,
    TeacherMessage,
)

logger = logging.getLogger(__name__)

MASTER_PROMPT = """You are the Master in Debug2Learn — an inspiring, Socratic AI debugging mentor.
Your philosophy is to guide developers to discover the solution through their own thinking.

RULES:
1. NEVER output the fixed code snippet.
2. Ground all hints and questions in the Solver's diagnosed root cause and logic analysis.
3. Keep questions specific to the actual bug, variable names, and functions rather than generic programming advice.
4. Progressive hint levels:
   - Level 1 (Nudge): Ask the developer to inspect what the data/marker represents (e.g. what '[x]' means).
   - Level 2 (Clue): Ask whether items with that marker should be included in or excluded from the desired count.
   - Level 3 (Direct Clue): Point directly to the filter condition in the code without writing the code fix.
"""


class MasterAgent(BaseAgent):
    """
    👑 Master — Socratic debugging mentor offering progressive hints and guidance.
    """

    def __init__(self, config: AppConfig):
        super().__init__(config, system_prompt=MASTER_PROMPT)

    def generate_initial_guidance(
        self,
        request_context: RequestContext,
        plan: DebuggingPlan,
    ) -> str:
        """Create the opening Socratic introduction for the developer based on Solver's plan."""
        step1 = plan.steps[0] if plan.steps else None
        target = plan.root_cause_location or plan.bug_location or "the source code"
        failure_loc = plan.failure_location or (f"test suite" if "test" in str(request_context.relevant_files) else "")

        prompt = f"""Generate an opening message for the developer:
Symptom: {request_context.symptom}
Failure Caught At: {failure_loc or 'Tests'}
Suspected Root Cause: {target}
Target Logic: {plan.relevant_logic}
Step 1: {step1.description if step1 else 'Inspect the code'}

Instructions:
1. Welcome them as the Debug Master.
2. Note that while tests flagged the issue at {failure_loc or 'the test runner'}, the logic originates in {target}.
3. Ask an engaging Socratic question based on Step 1 to kick off their investigation.
Keep it under 4 sentences. Do NOT give away the fix."""

        if self._model and self.config.groq.api_key:
            try:
                return self._send_sync(prompt)
            except Exception as e:
                logger.error(f"Master initial guidance failed: {e}")
                if is_groq_quota_error(e):
                    return "Groq is unavailable because its API quota has been reached. No AI guidance was generated."

        # Tailored fallback
        loc_str = f" `{target}`" if target else " the implementation"
        fail_str = f" (detected by `{failure_loc}`)" if failure_loc else ""
        
        if "[x]" in request_context.raw_input or "count_pending" in target:
            return (
                f"👑 **Debug Master**: Welcome to your debugging quest! The failure was caught{fail_str}, "
                f"but the root cause lies inside{loc_str}.\n\n"
                f"Let's start with the data: look closely at the tasks in `test_todo.py`. "
                f"What does the marker `'[x]'` represent, and what is `count_pending()` supposed to count?"
            )

        return (
            f"👑 **Debug Master**: Welcome! The failure was detected{fail_str}, pointing our investigation to{loc_str}.\n\n"
            f"Step 1: Look at the inputs and expectations: what do you notice about the data right before the calculation returns?"
        )

    def get_progressive_hint(
        self,
        step: DebuggingStep,
        current_hint_count: int,
        code_context: str = "",
        plan: DebuggingPlan | None = None,
        request_context: RequestContext | None = None,
    ) -> Hint:
        """
        Generate a simple progressive hint:
        - 0 prior hints -> Level 1: Nudge (inspect what markers/data signify)
        - 1 prior hint  -> Level 2: Clue (should completed tasks be in pending count?)
        - 2+ prior hints -> Level 3: Direct Clue (point toward list comprehension condition)
        """
        if current_hint_count == 0:
            level = HintLevel.CONCEPTUAL
            level_name = "Nudge"
            prompt_instruction = (
                "Give a gentle conceptual nudge based specifically on the diagnosed root cause. "
                "Ask the learner to inspect the relevant function, variable, or behavior."
            )
        elif current_hint_count == 1:
            level = HintLevel.DIRECTIONAL
            level_name = "Clue"
            prompt_instruction = (
                "Give a directional clue based specifically on the diagnosed logic issue. "
                "Help the learner narrow down the relevant condition or behavior without revealing the fix."
            )
        else:
            level = HintLevel.SPECIFIC
            level_name = "Direct Clue"
            prompt_instruction = (
                "Give a specific clue pointing toward the exact problematic logic identified by the Solver, "
                "without writing the solution code."
            )

        hypothesis = plan.hypothesis if plan else ""
        relevant_logic = plan.relevant_logic if plan else ""
        root_cause = plan.root_cause_location if plan else (step.target_symbol or step.target_file)

        prompt = f"""Generate a progressive debugging hint ({level_name}):
Current Step: {step.title}
Step Description: {step.description}
Root Cause Location: {root_cause}
Diagnosed Logic Issue: {relevant_logic}
Hypothesis: {hypothesis}
Code Context:
```python
{code_context[:1500]}
```

Level Instruction: {prompt_instruction}
Rules:
- 1-2 friendly, impactful sentences.
- NEVER write the solution code (do not write 'not task.startswith').
- Lead the developer to realize the answer themselves."""

        content = ""
        if self._model and self.config.groq.api_key:
            try:
                content = self._send_sync(prompt).strip()
            except Exception as e:
                logger.error(f"Master hint generation failed: {e}")
                if is_groq_quota_error(e):
                    content = "Groq is unavailable because its API quota has been reached. No AI hint was generated."

        if not content:
            target = step.target_symbol or step.target_file or "the relevant code"
            logic = relevant_logic or hypothesis or "the diagnosed behavior"

            if level == HintLevel.CONCEPTUAL:
                content = (
                    f"Look closely at `{target}`. "
                    f"What behavior described by the diagnosis — {logic} — should you verify first?"
                )
            elif level == HintLevel.DIRECTIONAL:
                content = (
                    f"Focus on `{target}` and compare its current behavior with the expected behavior. "
                    f"Which part of the logic could explain the diagnosed issue?"
                )
            else:
                content = (
                    f"Inspect the specific logic in `{target}` identified by the Solver. "
                    f"What small change would make its behavior match the expected result?"
        )

        return Hint(
            level=level,
            content=content,
            step_number=step.step_number,
            concept=step.concept or (plan.concept if plan else ""),
        )

    def answer_developer_question(
        self,
        question: str,
        session_state: SessionState,
        recent_code: str = "",
    ) -> str:
        """Answer a question from the developer using Socratic method grounded in the Solver's plan."""
        from debug2learn.core.models import ValidationState, SessionPhase
        if (
            session_state.validation_state in (ValidationState.QUEST_COMPLETED, ValidationState.TEST_PASSED)
            or session_state.phase in (SessionPhase.QUEST_COMPLETED, SessionPhase.TEST_PASSED, SessionPhase.COMPLETED)
        ):
            return (
                "🎉 Excellent! Your tests passed.\n\n"
                "You identified the root cause, fixed the code yourself,\n"
                "and proved that your solution works.\n\n"
                "+100 XP\n"
                "🏆 Quest Complete!"
            )

        plan = session_state.debugging_plan
        step = plan.steps[plan.current_step] if plan and plan.current_step < len(plan.steps) else None

        prompt = f"""The developer asked a question during debugging:
Question: {question}

Solver Diagnosis:
Root Cause: {plan.root_cause_location if plan else 'Implementation'}
Logic Issue: {plan.relevant_logic if plan else 'Discrepancy'}
Current Step: {step.title if step else 'Investigation'}

Code Context:
```python
{recent_code[:1200]}
```

Answer their question Socratically:
- Explain the underlying concept.
- Relate it to their specific function and variables.
- NEVER write out the fix.
- End with a guiding question."""

        if self._model and self.config.groq.api_key:
            try:
                return self._send_sync(prompt)
            except Exception as e:
                logger.error(f"Master Q&A failed: {e}")
                if is_groq_quota_error(e):
                    return "Groq is unavailable because its API quota has been reached. No AI answer was generated."

        # Contextual fallback when Groq is unavailable or quota-limited.
        question_lower = question.lower()
        if any(token in question_lower for token in ("remove_task", "importerror", "pytest", "import")):
            if "pytest" in question_lower or "importerror" in question_lower:
                return (
                    "👑 **Debug Master**: Pytest stops during collection because Python must import the test module "
                    "before it can run any test. What name does `test_todo.py` request from `todo.py`, and which "
                    "definition is missing?"
                )
            if "remove_task" in question_lower:
                return (
                    "👑 **Debug Master**: `remove_task` is part of the module interface expected by the test. "
                    "Trace the test's inputs and expected list after removal: what should happen when the requested "
                    "task is present, and how should the function communicate the updated list?"
                )
            return (
                "👑 **Debug Master**: Imports connect the test module to the functions in `todo.py`. "
                "Which imported name cannot be resolved, and what does that tell you about the source module's API?"
            )

        if "[x]" in question_lower or "count_pending" in question_lower:
            return (
                "👑 **Debug Master**: That's a perceptive question! In Python, list comprehensions can filter elements "
                "using an `if` clause. If you want to keep only items where a condition is *false*, how do you invert a boolean expression?"
            )

        fallback_questions = [
            f"👑 **Debug Master**: For `{question}`, identify the smallest input that demonstrates the behavior. What value should the function produce before you inspect the implementation?",
            f"👑 **Debug Master**: Relate `{question}` to the current debugging step. Which line, symbol, or test assertion would provide the strongest evidence?",
            f"👑 **Debug Master**: A useful next move for `{question}` is to compare the expected and observed states. What changed between those two moments?",
        ]
        prior_questions = sum(1 for message in session_state.messages if message.role == "developer")
        return fallback_questions[(prior_questions - 1) % len(fallback_questions)]
