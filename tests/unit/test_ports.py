"""Unit tests verifying abstract contracts of domain ports."""

import pytest
from painkiller.core.ports.issue_tracker import IssueTrackerPort
from painkiller.core.ports.sandbox import SandboxPort
from painkiller.core.ports.git import GitPort
from painkiller.core.ports.llm import LLMPort


def test_ports_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        IssueTrackerPort()  # type: ignore
    with pytest.raises(TypeError):
        SandboxPort()  # type: ignore
    with pytest.raises(TypeError):
        GitPort()  # type: ignore
    with pytest.raises(TypeError):
        LLMPort()  # type: ignore
