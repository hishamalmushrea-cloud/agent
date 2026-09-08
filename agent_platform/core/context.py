"""Context / message history management.

Keeps a bounded conversation history for the LLM, injecting tool results and
observations as structured messages so the model can reason over actual state.
"""

from __future__ import annotations

from agent_platform.models.schemas import Message, Role, Task

_MAX_MESSAGES = 60


class ContextBuilder:
    def __init__(self, max_messages: int = _MAX_MESSAGES) -> None:
        self.max_messages = max_messages

    def build(self, task: Task, system_prompt: str) -> list[dict]:
        msgs: list[dict] = [{"role": "system", "content": system_prompt}]
        recent = task.messages[-self.max_messages :]
        for m in recent:
            role = "assistant" if m.role == Role.ASSISTANT else (
                "tool" if m.role == Role.TOOL else "user")
            content = m.content
            if role == "tool":
                msgs.append({"role": "tool", "name": m.meta.get("tool", m.role), "content": content})
            else:
                msgs.append({"role": role, "content": content})
        return msgs

    def add_message(self, task: Task, role: Role, content: str, meta: dict | None = None,
                    tool_identity: str = "") -> Message:
        msg = Message(role=role, content=content, meta=meta or {})
        if tool_identity:
            msg.meta["tool"] = tool_identity
        task.messages.append(msg)
        return msg
