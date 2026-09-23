"""Unit tests for the Unreal Agent harness."""

import json
from unittest.mock import MagicMock
import pytest

from painkiller.cli.unreal_run import parse_unreal_line
from painkiller.core.domain.models import AgentEventType

SESSION = "12345678-1234-4234-8234-123456789012"


def test_parse_unreal_model_response():
    line = json.dumps({
        "Sequence": 1,
        "Kind": "model_response",
        "Data": {
            "TurnID": "turn-1",
            "Response": {
                "Output": [
                    {
                        "Type": "message",
                        "Data": {
                            "Role": "assistant",
                            "Text": "Olá! Sou o Unreal Agent.",
                        }
                    }
                ],
                "Usage": {
                    "InputTokens": 120,
                    "OutputTokens": 45,
                }
            }
        }
    })
    events = parse_unreal_line(line)
    assert len(events) == 2
    assert events[0].type == AgentEventType.ASSISTANT
    assert events[0].text == "Olá! Sou o Unreal Agent."
    assert events[1].type == AgentEventType.RESULT
    assert events[1].text == "Olá! Sou o Unreal Agent."


def test_parse_unreal_tool_call():
    line = json.dumps({
        "Sequence": 2,
        "Kind": "model_response",
        "Data": {
            "TurnID": "turn-1",
            "Response": {
                "Output": [
                    {
                        "Type": "tool_call",
                        "Data": {
                            "CallID": "call-1",
                            "Name": "bash",
                            "Arguments": "pytest",
                        }
                    }
                ]
            }
        }
    })
    events = parse_unreal_line(line)
    assert len(events) == 1
    assert events[0].type == AgentEventType.TOOL_USE
    assert events[0].text == "bash"


def test_parse_unreal_tool_status():
    line = json.dumps({
        "Sequence": 3,
        "Kind": "tool_call_status",
        "Data": {
            "TurnID": "turn-1",
            "CallID": "call-1",
            "Status": {"Error": ""},
            "Operations": [{"ID": "op-1", "Status": "completed"}]
        }
    })
    events = parse_unreal_line(line)
    assert len(events) == 1
    assert events[0].type == AgentEventType.TOOL_RESULT


def test_parse_unreal_error_event():
    line = json.dumps({
        "type": "error",
        "message": "authentication failed: invalid API key",
    })
    events = parse_unreal_line(line)
    assert len(events) == 1
    assert events[0].type == AgentEventType.ERROR
    assert "authentication failed" in events[0].text
