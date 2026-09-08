"""What a built request actually carries."""

import pytest

from vollama.chat import client
from vollama.config.presets import Preset


@pytest.fixture(autouse=True)
def _forget_renames():
    """Which endpoints take which name is a module global, so no test inherits it."""
    client._RENAMED.clear()


def _request(parameters):
    preset = Preset(
        base_url="http://localhost:11434/v1", model="a-model", parameters=parameters
    )
    return client.build(preset)._request([])


def test_a_parameter_the_preset_left_empty_is_not_sent():
    """Empty means silence, so the server is left to use its own default."""
    request = _request({"temperature": 0.5})
    assert request["temperature"] == 0.5
    assert "top_p" not in request
    assert "stop" not in request
    assert "max_tokens" not in request


def test_only_the_parameters_the_server_knows_are_sent():
    """A schema name no OpenAI endpoint takes stays local."""
    request = _request({"temperature": 0.5, "num_ctx": 4096})
    assert set(request) == {"model", "messages", "temperature"}


class _Refusing:
    """An endpoint that refuses `max_tokens` by name, the way OpenAI's do."""

    def __init__(self, refusals=1):
        self.refusals = refusals
        self.requests = []
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **request):
        self.requests.append(request)
        if self.refusals > 0:
            self.refusals -= 1
            raise _bad_request(
                "Unsupported parameter: 'max_tokens' is not supported with "
                "this model. Use 'max_completion_tokens' instead."
            )
        return "a reply"


def _bad_request(message):
    import httpx
    from openai import BadRequestError

    return BadRequestError(
        message,
        response=httpx.Response(400, request=httpx.Request("POST", "http://x")),
        body=None,
    )


def _client(api, model="a-model"):
    return client.Client(api=api, model=model, options={}, max_tokens=100)


def test_a_refused_max_tokens_is_sent_again_under_the_other_name():
    """The server names the field it wants; the retry uses it."""
    api = _Refusing()
    assert _client(api).stream([]) == "a reply"
    assert "max_tokens" in api.requests[0]
    assert api.requests[1]["max_completion_tokens"] == 100
    assert "max_tokens" not in api.requests[1]


def test_the_rename_is_remembered_for_that_endpoint_and_model():
    """One correction, not one per message."""
    api = _Refusing()
    _client(api).stream([])
    assert _client(api).stream([]) == "a reply"
    assert len(api.requests) == 3
    assert "max_completion_tokens" in api.requests[2]


def test_a_refusal_that_is_not_about_the_name_is_raised():
    """Only this one wording is answered with a second request."""
    from openai import BadRequestError

    class Broken(_Refusing):
        def create(self, **request):
            self.requests.append(request)
            raise _bad_request("Invalid value for 'temperature'.")

    api = Broken()
    with pytest.raises(BadRequestError):
        _client(api).stream([])
    assert len(api.requests) == 1
