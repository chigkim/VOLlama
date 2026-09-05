"""The tool registry: what the model is offered, and how a call reaches it."""

import json

import pytest

from vollama.tools import registry


def test_every_tool_is_offered_exactly_once():
    names = [tool.name for tool in registry.REGISTRY]
    assert names == ["run", "poll", "read", "write", "edit"]
    assert sorted(registry.BY_NAME) == sorted(names)


def test_free_calls_are_the_ones_that_only_look():
    free = [tool.name for tool in registry.REGISTRY if tool.free]
    assert free == ["poll", "read"]
    assert registry.is_free("poll") and not registry.is_free("run")


def test_every_schema_is_shaped_the_way_the_api_wants():
    for tool in registry.REGISTRY:
        function = tool.schema["function"]
        assert tool.schema["type"] == "function"
        assert function["description"].strip()
        assert function["parameters"]["type"] == "object"
        for name in function["parameters"].get("required", []):
            assert name in function["parameters"]["properties"]


# Every failure is worded rather than raised: the model is the one who has to
# read it, and a raise would end the turn instead of correcting the model.
def test_an_unknown_tool_is_answered_not_raised():
    assert registry.call("frobnicate", "{}") == "There is no tool named frobnicate."


def test_arguments_that_are_not_json_are_answered():
    assert "Could not read the arguments as JSON" in registry.call("read", "{oops")


def test_arguments_that_are_not_an_object_are_answered():
    assert registry.call("read", "[1, 2]") == "The arguments must be a JSON object."


def test_the_wrong_argument_names_are_answered_by_name():
    result = registry.call("read", json.dumps({"file": "a.txt"}))
    assert result.startswith("Wrong arguments for read:")


def test_describe_falls_back_to_the_raw_arguments_when_they_will_not_parse():
    assert registry.describe("run", "{oops") == "{oops"


def test_describe_uses_each_tool_s_own_summary():
    assert registry.describe("run", '{"command": "git status"}') == "git status"
    assert registry.describe("edit", '{"path": "a.py", "edits": [1, 2]}') == (
        "edit a.py (2 edits)"
    )


def test_the_environment_tells_the_model_what_it_cannot_work_out(isolated, tmp_path):
    isolated.workdir = str(tmp_path)
    described = registry.environment()
    assert str(tmp_path) in described
    assert "Shell running your command" in described
    assert "Python on PATH" in described


@pytest.mark.parametrize("budget", [registry.MAX_TOOL_ROUNDS, registry.MAX_TOOL_CALLS])
def test_the_budgets_are_positive(budget):
    assert budget > 0
