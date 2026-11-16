"""Tests for the part that talks to Claude, using the fake API server."""

import pytest

from fake_api import FakeAnthropic, api_error, sse_events
from sidekick.claude_client import FALLBACK_BETA, AskError, ClaudeClient, Conversation
from sidekick.config import Settings
from sidekick.prompts import SYSTEM_PROMPT


@pytest.fixture
def api():
    server = FakeAnthropic().start()
    yield server
    server.stop()


def make_client(api, **settings):
    return ClaudeClient(Settings(**settings), api_key="test-key", base_url=api.base_url, max_retries=0)


def ask(client, convo, content="What is 2+2?"):
    pieces = []
    result = client.ask(convo, content, pieces.append)
    return result, pieces


def test_answer_is_streamed_piece_by_piece(api):
    api.script.append(sse_events(["The answer", " is 4."]))
    convo = Conversation()
    result, pieces = ask(make_client(api), convo)

    assert pieces == ["The answer", " is 4."]
    assert result.text == "The answer is 4."
    assert result.stop_reason == "end_turn"
    assert result.model == "claude-opus-5-5"
    assert not result.refused and not result.cancelled and result.notice == ""
    # 120 input tokens at $4/M + 45 output tokens at $20/M
    assert result.cost_usd == pytest.approx((120 * 4 + 45 * 20) / 1_000_000)


def test_request_uses_the_documented_settings(api):
    ask(make_client(api), Conversation())
    sent = api.requests[0]
    body = sent["body"]

    assert sent["path"].startswith("/v1/messages")
    # the key travels in a header (which header depends on the library version)
    credentials = sent["headers"].get("x-api-key", "") + sent["headers"].get("authorization", "")
    assert "test-key" in credentials
    assert body["model"] == "claude-opus-5-5"
    assert body["max_tokens"] == 16000
    assert body["stream"] is True
    assert body["system"] == SYSTEM_PROMPT
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "medium"}
    # backup model requested, with its opt-in header
    assert body["fallbacks"] == "default"
    assert FALLBACK_BETA in sent["headers"]["anthropic-beta"]
    # a short first question is not worth caching
    assert "cache_control" not in body
    assert body["messages"] == [{"role": "user", "content": "What is 2+2?"}]


def test_model_and_effort_come_from_settings(api):
    ask(make_client(api, model="claude-sonnet-5-5", effort="low"), Conversation())
    body = api.requests[0]["body"]
    assert body["model"] == "claude-sonnet-5-5"
    assert body["output_config"] == {"effort": "low"}
    assert body["fallbacks"] == "default"


def test_haiku_gets_no_backup_model_request(api):
    api.script.append(sse_events(model="claude-haiku-5-5"))
    ask(make_client(api, model="claude-haiku-5-5"), Conversation())
    sent = api.requests[0]
    assert "fallbacks" not in sent["body"]
    assert FALLBACK_BETA not in sent["headers"].get("anthropic-beta", "")


def test_follow_up_sends_history_back_unchanged(api):
    client = make_client(api)
    convo = Conversation()
    api.script.append(sse_events(["4"]))
    ask(client, convo, "What is 2+2?")
    api.script.append(sse_events(["8"]))
    ask(client, convo, "And doubled?")

    body = api.requests[1]["body"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]
    assistant = body["messages"][1]["content"]
    # Claude's hidden thinking block goes back exactly as received
    assert assistant[0]["type"] == "thinking" and assistant[0]["signature"] == "sig-abc"
    assert assistant[1] == {"type": "text", "text": "4"}
    assert body["messages"][2] == {"role": "user", "content": "And doubled?"}
    # follow-ups reuse the earlier part of the conversation from the cache
    assert body["cache_control"] == {"type": "ephemeral"}
    assert len(convo.messages) == 4


def test_picture_in_first_message_turns_caching_on(api):
    content = [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aGk="}},
        {"type": "text", "text": "What is this?"},
    ]
    convo = Conversation()
    ask(make_client(api), convo, content)
    body = api.requests[0]["body"]
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][0]["content"][0]["type"] == "image"
    assert convo.has_attachment


def test_refusal_is_reported_and_not_kept(api):
    api.script.append(
        sse_events(
            [], stop_reason="refusal", thinking=False,
            stop_details={"type": "refusal", "category": "cyber", "explanation": "declined"},
        )
    )
    convo = Conversation()
    result, pieces = ask(make_client(api), convo)
    assert result.refused
    assert "declined" in result.notice
    assert pieces == []
    assert convo.messages == []  # the declined question is not carried forward


def test_cut_off_answer_says_so(api):
    api.script.append(sse_events(["Part one"], stop_reason="max_tokens"))
    convo = Conversation()
    result, _ = ask(make_client(api), convo)
    assert "cut off" in result.notice
    assert len(convo.messages) == 2  # kept, so "continue" works


def test_backup_model_answer_is_labelled_and_history_follows_the_rule(api):
    client = make_client(api)
    convo = Conversation()
    api.script.append(sse_events(["Here you go."], model="claude-opus-4-8", fallback_to="claude-opus-4-8"))
    result, _ = ask(client, convo)

    assert result.text == "Here you go."
    assert result.model == "claude-opus-4-8"
    assert "backup model (claude-opus-4-8)" in result.notice
    # priced with the backup model's rates ($5 / $25)
    assert result.cost_usd == pytest.approx((120 * 5 + 45 * 25) / 1_000_000)

    kept = [b.type for b in convo.messages[1]["content"]]
    # the thinking block from BEFORE the switch is dropped; everything after stays
    assert kept == ["fallback", "thinking", "text"]

    api.script.append(sse_events(["ok"], model="claude-opus-4-8"))
    ask(client, convo, "thanks")
    echoed = api.requests[1]["body"]["messages"][1]["content"]
    assert echoed[0]["type"] == "fallback"
    assert echoed[0]["from"] == {"model": "claude-opus-5-5"}
    assert echoed[0]["to"] == {"model": "claude-opus-4-8"}
    assert echoed[1]["signature"] == "sig-fallback"


def test_cost_adds_up_every_attempt_when_listed(api):
    iterations = [
        {"type": "message", "model": "claude-opus-5-5", "input_tokens": 100, "output_tokens": 10},
        {"type": "fallback_message", "model": "claude-opus-4-8", "input_tokens": 100, "output_tokens": 50},
    ]
    api.script.append(sse_events(["ok"], model="claude-opus-4-8", iterations=iterations))
    result, _ = ask(make_client(api), Conversation())
    expected = (100 * 4 + 10 * 20 + 100 * 5 + 50 * 25) / 1_000_000
    assert result.cost_usd == pytest.approx(expected)


def test_stop_button_cancels_and_keeps_nothing(api):
    api.event_delay = 0.02
    api.script.append(sse_events(["one", " two", " three", " four"]))
    convo = Conversation()
    pieces = []
    result = make_client(api).ask(convo, "hi", pieces.append, should_stop=lambda: len(pieces) >= 1)
    assert result.cancelled
    assert pieces == ["one"]
    assert convo.messages == []


@pytest.mark.parametrize(
    "status, kind, message, expected, needs_key",
    [
        (401, "authentication_error", "invalid x-api-key", "API key was not accepted", True),
        (403, "permission_error", "not allowed here", "not allowed", False),
        (404, "not_found_error", "model: claude-opus-5-5", "cannot use the model", False),
        (413, "request_too_large", "too big", "too much to send", False),
        (429, "rate_limit_error", "slow down", "Too many requests", False),
        (400, "invalid_request_error", "Your credit balance is too low to access the Anthropic API.", "no credit left", False),
        (402, "billing_error", "payment required", "no credit left", False),
        (400, "invalid_request_error", "messages: something odd", "something odd", False),
        (500, "api_error", "oops", "servers are busy", False),
        (529, "overloaded_error", "Overloaded", "servers are busy", False),
    ],
)
def test_errors_become_plain_sentences(api, status, kind, message, expected, needs_key):
    api.script.append(api_error(status, kind, message))
    convo = Conversation()
    with pytest.raises(AskError) as caught:
        ask(make_client(api), convo)
    assert expected in str(caught.value)
    assert caught.value.needs_key is needs_key
    assert convo.messages == []


def test_no_internet_is_reported_clearly():
    client = ClaudeClient(Settings(), api_key="k", base_url="http://127.0.0.1:9", max_retries=0)
    with pytest.raises(AskError) as caught:
        client.ask(Conversation(), "hi", lambda _t: None)
    assert "internet connection" in str(caught.value)


def test_missing_key_is_reported_clearly(api, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    client = ClaudeClient(Settings(), api_key=None, base_url=api.base_url, max_retries=0)
    with pytest.raises(AskError) as caught:
        client.ask(Conversation(), "hi", lambda _t: None)
    assert caught.value.needs_key


def test_account_without_backup_feature_still_works(api):
    api.script.append(
        api_error(400, "invalid_request_error", "Unexpected value(s) `server-side-fallback-2026-07-01` for the `anthropic-beta` header.")
    )
    api.script.append(sse_events(["Fine."]))
    client = make_client(api)
    result, _ = ask(client, Conversation())

    assert result.text == "Fine."
    assert len(api.requests) == 2
    assert "fallbacks" in api.requests[0]["body"]
    assert "fallbacks" not in api.requests[1]["body"]
    # and it stays off for the rest of the session
    api.script.append(sse_events(["Again."]))
    ask(client, Conversation())
    assert "fallbacks" not in api.requests[2]["body"]


def test_token_count(api):
    client = make_client(api)
    api.count_reply = {"input_tokens": 4321}
    assert client.count_input_tokens(Conversation(), "hello") == 4321
    sent = api.count_requests[0]["body"]
    assert sent["model"] == "claude-opus-5-5"
    assert sent["messages"] == [{"role": "user", "content": "hello"}]

    api.count_reply = api_error(500, "api_error", "oops")
    assert client.count_input_tokens(Conversation(), "hello") is None
