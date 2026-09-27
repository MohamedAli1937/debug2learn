from __future__ import annotations

import logging

from debug2learn.agents.base import BaseAgent, is_groq_quota_error
from debug2learn.config.settings import AppConfig
from debug2learn.core.models import (
    DebuggingPlan,
    DebuggingStep,
    Hint,
    HintLevel,
    RequestContext,
    SessionState,
)

logger = logging.getLogger(__name__)


MASTER_PROMPT = """You are the Master in Debug2Learn — an inspiring, Socratic AI debugging mentor.

Your philosophy is to guide developers to discover the solution through their own thinking.

RULES:

1. NEVER output the fixed code snippet.

2. Ground all hints and questions in the Solver's diagnosed root cause,
   hypothesis, and logic analysis.

3. Keep questions specific to the actual bug, variable names, functions,
   files, tests, and observed behavior.

4. NEVER assume a specific bug pattern.
   Do not introduce concepts, variables, functions, markers, or conditions
   that are not supported by the Solver's diagnosis or provided code.

5. Progressive hint levels:

   - Level 1 (Nudge):
     Guide the developer to inspect the relevant function, variable,
     input, output, or behavior identified by the Solver.

   - Level 2 (Clue):
     Help the developer narrow down the specific logic issue identified
     by the Solver.

   - Level 3 (Direct Clue):
     Point toward the exact problematic logic identified by the Solver,
     without revealing or writing the solution.

6. Every hint must be relevant to the current debugging step.

7. NEVER invent a different root cause.

8. NEVER reveal the exact fix.

9. NEVER provide corrected code.

10. Adapt the guidance to whatever diagnosis the Solver provides.
"""


class MasterAgent(BaseAgent):
    """
    Master — Socratic debugging mentor offering progressive hints
    and guidance grounded in the Solver's diagnosis.
    """

    def __init__(self, config: AppConfig):
        super().__init__(config, system_prompt=MASTER_PROMPT)

    def generate_initial_guidance(
        self,
        request_context: RequestContext,
        plan: DebuggingPlan,
    ) -> str:
        """Create the opening Socratic introduction based on Solver's plan."""

        step1 = plan.steps[0] if plan.steps else None

        target = (
            plan.root_cause_location
            or plan.bug_location
            or "the source code"
        )

        failure_loc = plan.failure_location or (
            "test suite"
            if "test" in str(request_context.relevant_files).lower()
            else ""
        )

        prompt = f"""Generate an opening message for the developer.

Symptom:
{request_context.symptom}

Raw Bug Report:
{request_context.raw_input}

Failure Caught At:
{failure_loc or "Tests"}

Solver Root Cause Location:
{target}

Solver Logic Analysis:
{plan.relevant_logic}

Solver Hypothesis:
{plan.hypothesis}

Concept:
{plan.concept}

Step 1:
{step1.description if step1 else "Inspect the relevant code."}

Target File:
{step1.target_file if step1 else "Unknown"}

Target Symbol:
{step1.target_symbol if step1 else "Unknown"}

Instructions:

1. Welcome the developer as the Debug Master.
2. Explain that the failure was detected at the reported location,
   while the Solver identified the relevant root cause.
3. Ask ONE engaging Socratic question based on Step 1 and the Solver diagnosis.
4. Use actual names from the diagnosis when useful.
5. Do not introduce unrelated concepts.
6. Do not assume a specific bug pattern.
7. Do not reveal the solution.
8. Do not provide corrected code.
9. Keep it under 4 sentences.
"""

        if self._model and self.config.groq.api_key:
            try:
                content = self._send_sync(prompt).strip()

                if content:
                    return content

            except Exception as e:
                logger.error(f"Master initial guidance failed: {e}")

                if is_groq_quota_error(e):
                    logger.warning(
                        "Groq quota reached during initial guidance."
                    )

        target_display = f"`{target}`"

        failure_display = (
            f"`{failure_loc}`"
            if failure_loc
            else "`the test suite`"
        )

        step_description = (
            step1.description
            if step1
            else "Inspect the relevant implementation."
        )

        return (
            "👑 **Debug Master**: Welcome to your debugging quest!\n\n"
            f"The failure was detected by {failure_display}, while the "
            f"Solver points our investigation toward {target_display}.\n\n"
            f"Step 1: {step_description} "
            "What do you notice that could explain the behavior identified "
            "by the Solver?"
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
        Generate progressive hints grounded in the Solver diagnosis.

        0 prior hints -> Level 1: Nudge
        1 prior hint -> Level 2: Clue
        2+ prior hints -> Level 3: Direct Clue
        """

        if current_hint_count <= 0:
            level = HintLevel.CONCEPTUAL
            level_name = "Nudge"
            prompt_instruction = (
                "Give a gentle conceptual nudge based specifically on the "
                "Solver's diagnosed root cause. Guide the learner to inspect "
                "the relevant function, variable, input, output, or behavior."
            )

        elif current_hint_count == 1:
            level = HintLevel.DIRECTIONAL
            level_name = "Clue"
            prompt_instruction = (
                "Give a directional clue based specifically on the Solver's "
                "diagnosed logic issue. Help the learner narrow down the "
                "relevant condition, operation, or behavior without revealing "
                "the fix."
            )

        else:
            level = HintLevel.SPECIFIC
            level_name = "Direct Clue"
            prompt_instruction = (
                "Give a specific clue pointing toward the exact problematic "
                "logic identified by the Solver, without revealing or writing "
                "the solution."
            )

        hypothesis = plan.hypothesis if plan else ""
        relevant_logic = plan.relevant_logic if plan else ""

        root_cause = (
            plan.root_cause_location
            if plan
            else (
                step.target_symbol
                or step.target_file
                or "the relevant code"
            )
        )

        concept = (
            plan.concept
            if plan
            else getattr(step, "concept", "")
        )

        prompt = f"""Generate a progressive debugging hint ({level_name}).

Current Step:
{step.title}

Step Description:
{step.description}

Target File:
{step.target_file}

Target Symbol:
{step.target_symbol}

Root Cause Location:
{root_cause}

Diagnosed Logic Issue:
{relevant_logic}

Solver Hypothesis:
{hypothesis}

Concept:
{concept}

Code Context:
{code_context[:2000]}

Level Instruction:
{prompt_instruction}

Rules:

- Write 1-2 friendly, impactful sentences.
- Ground the hint ONLY in the Solver diagnosis and provided code.
- Use actual function names, variables, files, tests, or behavior when useful.
- Do not introduce unrelated examples.
- Do not assume a specific bug pattern.
- Do not invent missing information.
- NEVER write the solution code.
- NEVER reveal the exact fix.
- NEVER state the corrected expression or implementation.
- Lead the developer to discover the answer themselves.
"""

        content = ""

        if self._model and self.config.groq.api_key:
            try:
                content = self._send_sync(prompt).strip()

            except Exception as e:
                logger.error(f"Master hint generation failed: {e}")

                if is_groq_quota_error(e):
                    logger.warning(
                        "Groq quota reached during hint generation."
                    )

        if not content:
            target = (
                step.target_symbol
                or step.target_file
                or "the relevant code"
            )

            logic = (
                relevant_logic
                or hypothesis
                or "the diagnosed behavior"
            )

            if level == HintLevel.CONCEPTUAL:
                content = (
                    f"Look closely at `{target}`. "
                    f"What behavior described by the Solver's diagnosis — "
                    f"{logic} — should you verify first?"
                )

            elif level == HintLevel.DIRECTIONAL:
                content = (
                    f"Focus on `{target}` and compare its current behavior "
                    "with the expected behavior. "
                    "Which part of the logic could explain the diagnosed issue?"
                )

            else:
                content = (
                    f"Inspect the specific logic in `{target}` identified "
                    "by the Solver. "
                    "Which part of that logic is producing the observed "
                    "behavior instead of the expected one?"
                )

        return Hint(
            level=level,
            content=content,
            step_number=step.step_number,
            concept=(
                getattr(step, "concept", "")
                or (plan.concept if plan else "")
            ),
        )

    def answer_developer_question(
        self,
        question: str,
        session_state: SessionState,
        recent_code: str = "",
    ) -> str:
        """Answer developer questions using the Socratic method."""

        from debug2learn.core.models import ValidationState, SessionPhase

        if (
            session_state.validation_state
            in (
                ValidationState.QUEST_COMPLETED,
                ValidationState.TEST_PASSED,
            )
            or session_state.phase
            in (
                SessionPhase.QUEST_COMPLETED,
                SessionPhase.TEST_PASSED,
                SessionPhase.COMPLETED,
            )
        ):
            return (
                "🎉 Excellent! Your tests passed.\n\n"
                "You identified the root cause, fixed the code yourself,\n"
                "and proved that your solution works.\n\n"
                "+100 XP\n"
                "🏆 Quest Complete!"
            )

        plan = session_state.debugging_plan

        step = None

        if plan and plan.steps:
            current_step = getattr(plan, "current_step", 0)

            if 0 <= current_step < len(plan.steps):
                step = plan.steps[current_step]

        root_cause = (
            plan.root_cause_location
            if plan
            else "the implementation"
        )

        logic_issue = (
            plan.relevant_logic
            if plan and plan.relevant_logic
            else "the diagnosed discrepancy"
        )

        hypothesis = (
            plan.hypothesis
            if plan and plan.hypothesis
            else "the Solver's diagnosis"
        )

        prompt = f"""The developer asked a question during debugging.

Developer Question:
{question}

Solver Diagnosis:

Root Cause Location:
{root_cause}

Logic Issue:
{logic_issue}

Hypothesis:
{hypothesis}

Current Step:
{step.title if step else "Investigation"}

Step Description:
{step.description if step else "Inspect the diagnosed behavior."}

Target File:
{step.target_file if step else "Unknown"}

Target Symbol:
{step.target_symbol if step else "Unknown"}

Code Context:
{recent_code[:1600]}

Answer the developer using the Socratic method.

Rules:

- Answer the actual question.
- Explain the underlying concept clearly.
- Relate the explanation to the actual Solver diagnosis.
- Use real function names, variables, files, tests, and behavior when available.
- Do not introduce unrelated bug patterns.
- Do not assume a specific implementation.
- NEVER write the exact fix.
- NEVER provide corrected code.
- NEVER reveal the final answer directly.
- End with a guiding question that helps the developer reason further.
"""

        if self._model and self.config.groq.api_key:
            try:
                content = self._send_sync(prompt).strip()

                if content:
                    return content

            except Exception as e:
                logger.error(f"Master Q&A failed: {e}")

                if is_groq_quota_error(e):
                    logger.warning(
                        "Groq quota reached during Q&A."
                    )

        target = (
            step.target_symbol
            if step and step.target_symbol
            else (
                step.target_file
                if step and step.target_file
                else root_cause
            )
        )

        return (
            "👑 **Debug Master**: Let's stay focused on the Solver's diagnosis.\n\n"
            f"The investigation currently points to `{target}` because "
            f"{logic_issue}.\n\n"
            f"Think about `{target}` in relation to the expected behavior: "
            "what should happen, what actually happens, and what evidence "
            "in the code or test helps explain the difference?"
        )