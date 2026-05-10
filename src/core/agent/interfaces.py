"""
Protocol classes for everything Layer 2 calls out to.
All of Layer 2 talks only to these protocols, never to concrete classes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, AsyncIterator, Protocol, runtime_checkable

if TYPE_CHECKING:
    from src.core.schemas import PatientContext


@runtime_checkable
class TTSStreamLike(Protocol):
    async def feed(self, text: str) -> None: ...
    async def flush(self) -> None: ...
    async def cancel(self) -> None: ...
    async def close(self) -> None: ...

    @property
    def is_active(self) -> bool: ...


@runtime_checkable
class TTSFactoryLike(Protocol):
    async def open_stream(self, call_sid: str, voice_id: str) -> TTSStreamLike: ...


@runtime_checkable
class AnthropicLike(Protocol):
    async def stream_messages(
        self,
        model: str,
        system: list[dict],
        messages: list[dict],
        tools: list[dict],
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator["StreamEvent"]: ...


# ---------------------------------------------------------------------------
# Stream event types yielded by brain.stream_turn
# ---------------------------------------------------------------------------

class TextDelta:
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


class ToolUseStart:
    __slots__ = ("tool_use_id", "name")

    def __init__(self, tool_use_id: str, name: str) -> None:
        self.tool_use_id = tool_use_id
        self.name = name


class ToolUseInputDelta:
    __slots__ = ("tool_use_id", "partial_json")

    def __init__(self, tool_use_id: str, partial_json: str) -> None:
        self.tool_use_id = tool_use_id
        self.partial_json = partial_json


class ToolUseStop:
    __slots__ = ("tool_use_id", "name", "input")

    def __init__(self, tool_use_id: str, name: str, input: dict) -> None:
        self.tool_use_id = tool_use_id
        self.name = name
        self.input = input


class MessageStop:
    __slots__ = ("stop_reason", "full_assistant_message")

    def __init__(self, stop_reason: str, full_assistant_message: dict) -> None:
        self.stop_reason = stop_reason
        self.full_assistant_message = full_assistant_message


StreamEvent = TextDelta | ToolUseStart | ToolUseInputDelta | ToolUseStop | MessageStop


@runtime_checkable
class DBLike(Protocol):
    async def get_patient_by_phone(self, phone: str) -> object | None: ...
    async def create_patient(self, **fields: object) -> object: ...
    async def get_patient_by_id(self, patient_id: int) -> object | None: ...
    async def create_conversation(self, patient_id: int | None, call_sid: str, direction: str) -> int: ...
    async def end_conversation(self, conversation_id: int, tier_reached: str, summary: str) -> None: ...
    async def log_symptom(self, conversation_id: int, patient_id: int | None, symptom: str) -> None: ...
    async def log_vitals(self, conversation_id: int, patient_id: int | None, vitals: dict) -> None: ...
    async def get_latest_sms_vitals(self, patient_id: int) -> object | None: ...
    async def request_doctor_review(self, conversation_id: int, case_packet: dict) -> int: ...
    async def send_sms(self, to_phone: str, body: str) -> None: ...
    async def audit(self, actor: str, action: str, patient_id: int | None, conversation_id: int | None) -> None: ...
    async def register_patient(self, phone: str, first_name: str, gestational_stage: str, verbal_consent_given: bool) -> object: ...
