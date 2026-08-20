from typing import Any, Callable


class ProfessorAgent:
    """Facade for the stateful Realtime professor and its client tool loop."""

    name = "professor_agent"

    def run(self, create_session: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        session = create_session()
        session["agent"] = {
            "name": self.name,
            "mode": "realtime_tool_loop",
        }
        return session
