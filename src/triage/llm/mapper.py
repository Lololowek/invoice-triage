"""Mapper: (text, candidates) -> FieldMapping. The only place the pipeline touches a model."""

from __future__ import annotations

from typing import Protocol

from triage.candidates import Candidate
from triage.llm.client import ChatClient
from triage.llm.mapping import FieldMapping, MappingParseError, parse_mapping, response_json_schema
from triage.llm.prompt import build_messages


class Mapper(Protocol):
    name: str

    def map(self, text: str, candidates: list[Candidate]) -> FieldMapping: ...


class MappingError(RuntimeError):
    pass


class LLMMapper:
    """Asks the model for a mapping; on an unparseable answer retries once with the error."""

    def __init__(self, client: ChatClient, max_attempts: int = 2) -> None:
        self.client = client
        self.name = client.name
        self.max_attempts = max_attempts

    def map(self, text: str, candidates: list[Candidate]) -> FieldMapping:
        messages = build_messages(text, candidates)
        schema = response_json_schema()
        error: MappingParseError | None = None
        for _ in range(self.max_attempts):
            raw = self.client.complete(messages, schema, "invoice_field_mapping")
            try:
                return parse_mapping(raw)
            except MappingParseError as e:
                error = e
                messages = [
                    *messages,
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content": f"{e}\nReturn only JSON that matches the schema."},
                ]
        raise MappingError(
            f"model returned no valid mapping after {self.max_attempts} attempts: {error}"
        )
