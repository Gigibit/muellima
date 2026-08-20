"""Small dependency-free agent runner for bounded reasoning loops."""
from dataclasses import dataclass, field
from typing import Any, Callable


class AgentValidationError(ValueError):
    pass


def _usage_values(usage: Any) -> dict[str, int]:
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    if not isinstance(usage, dict):
        usage = {
            "input_tokens": getattr(usage, "input_tokens", 0),
            "output_tokens": getattr(usage, "output_tokens", 0),
            "total_tokens": getattr(usage, "total_tokens", 0),
        }
    input_tokens = max(0, int(usage.get("input_tokens") or 0))
    output_tokens = max(0, int(usage.get("output_tokens") or 0))
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": max(
            0,
            int(usage.get("total_tokens") or input_tokens + output_tokens),
        ),
    }


@dataclass
class AgentTrace:
    name: str
    attempts: int = 0
    validation_errors: list[str] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=lambda: {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
    })

    def add_usage(self, usage: Any) -> None:
        values = _usage_values(usage)
        for key, value in values.items():
            self.usage[key] += value

    def public_data(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "attempts": self.attempts,
            "validation_retries": len(self.validation_errors),
        }


class BoundedAgent:
    """Run, validate and retry an LLM task within a hard iteration limit."""

    name = "agent"

    def __init__(self, max_iterations: int = 2):
        self.max_iterations = min(max(int(max_iterations), 1), 3)

    def run(
        self,
        execute: Callable[[int, str], tuple[dict[str, Any], Any]],
        validate: Callable[[dict[str, Any]], str | None],
    ) -> dict[str, Any]:
        trace = AgentTrace(self.name)
        feedback = ""
        for attempt in range(1, self.max_iterations + 1):
            trace.attempts = attempt
            result, usage = execute(attempt, feedback)
            trace.add_usage(usage)
            feedback = validate(result) or ""
            if not feedback:
                result["_usage"] = trace.usage
                result["_agent"] = trace.public_data()
                return result
            trace.validation_errors.append(feedback)
        raise AgentValidationError(
            f"{self.name} non ha prodotto un risultato valido dopo "
            f"{self.max_iterations} tentativi: {feedback}"
        )
