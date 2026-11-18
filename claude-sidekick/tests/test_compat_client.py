"""Tests for answers from Gemini, Ollama or another OpenAI-compatible service,
using a fake service on this computer."""

import socket

import pytest

from fake_compat import FakeCompat, chunks, error
from sidekick.claude_client import AskError, Conversation
from sidekick.compat_client import PDF_NOT_SUPPORTED, CompatClient, to_chat_content
from sidekick.config import Settings
from sidekick.prompts import SYSTEM_PROMPT, build_first_message
from sidekick.attachments import Attachment


@pytest.fixture
def service():
    server = FakeCompat().start()
    yield server
    server.stop()


def client(service, kind="gemini", key="AIza-test", **settings):
    s = Settings(gemini_base_url=service.base_url, ollama_url=service.base_url,
                 custom_url=service.base_url, custom_model="my-model", custom_name="Groq", **settings)
    return CompatClient(s, kind, api_key=key)


def ask(c, convo, content="What is 2+2?"):
    pieces = []
    return c.ask(convo, content, pieces.append), pieces


def test_gemini_answer_streams_in(service):
    service.script.append(chunks(["The answer", " is 4."]))
    result, pieces = ask(client(service), Conversation())
    assert pieces == ["The answer", " is 4."]
    assert result.text == "The answer is 4."
    assert result.model == "gemini-3.5-flash-lite" and result.cost_usd is None and result.notice == ""

    sent = service.requests[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["headers"]["authorization"] == "Bearer AIza-test"
    assert sent["body"] == {
        "model": "gemini-3.5-flash-lite", "stream": True,
        "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": "What is 2+2?"}],
    }


def test_ollama_needs_no_key_and_follow_ups_carry_history(service):
    c = client(service, kind="ollama", key=None, ollama_model="gemma4:e4b")
    convo = Conversation()
    service.script.append(chunks(["4"]))
    ask(c, convo, "What is 2+2?")
    service.script.append(chunks(["8"]))
    ask(c, convo, "And doubled?")
    first, second = service.requests
    assert "authorization" not in first["headers"]
    assert second["body"]["model"] == "gemma4:e4b"
    assert second["body"]["messages"][1:] == [
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4"},
        {"role": "user", "content": "And doubled?"},
    ]


def test_first_message_becomes_plain_text_or_parts():
    window = None
    text_only = build_first_message("Why?", "=SUM(A1", window, None)
    assert to_chat_content(text_only) == "<copied_text>\n=SUM(A1\n</copied_text>\n\n<question>\nWhy?\n</question>"

    picture = Attachment("image", "", "image/png", b"\x89PNG", "1 x 1")
    parts = to_chat_content(build_first_message("What is this?", "", window, picture))
    assert parts[0] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw=="}}
    assert parts[1] == {"type": "text", "text": "<question>\nWhat is this?\n</question>"}

    pdf = Attachment("pdf", "a.pdf", "application/pdf", b"%PDF")
    with pytest.raises(AskError) as caught:
        to_chat_content(build_first_message("Summarize", "", window, pdf))
    assert str(caught.value) == PDF_NOT_SUPPORTED


def test_cut_off_and_declined_answers(service):
    service.script.append(chunks(["Part one"], finish="length"))
    convo = Conversation()
    result, _ = ask(client(service), convo)
    assert "cut off" in result.notice and len(convo.messages) == 2

    service.script.append(chunks([], finish="content_filter"))
    convo = Conversation()
    result, _ = ask(client(service), convo)
    assert result.refused and "declined" in result.notice and convo.messages == []


def test_your_own_prices_give_cost_estimates(service):
    c = client(service, prices={"gemini": [0.30, 2.50]})
    service.script.append(chunks(["ok"], usage={"prompt_tokens": 1000, "completion_tokens": 200}))
    result, _ = ask(c, Conversation())
    assert result.cost_usd == pytest.approx((1000 * 0.30 + 200 * 2.50) / 1_000_000)

    service.script.append(chunks(["ok" * 40]))  # no usage numbers: estimated from length
    result, _ = ask(c, Conversation())
    assert result.cost_usd is not None and result.cost_usd > 0


@pytest.mark.parametrize("kind, status, message, expected, needs_key", [
    ("gemini", 401, "API key not valid", "Gemini API key was not accepted", True),
    ("gemini", 404, "model not found", 'Gemini has no model called "gemini-3.5-flash-lite"', False),
    ("gemini", 429, "Resource has been exhausted", "Gemini's free limit is used up for now", False),
    ("gemini", 400, "Invalid argument", "It said: Invalid argument", False),
    ("gemini", 503, "overloaded", "having problems right now", False),
    ("ollama", 404, 'model "gemma4:e4b" not found', "ollama pull gemma4:e4b", False),
    ("custom", 401, "bad key", "Your Groq API key was not accepted", True),
    ("custom", 429, "slow down", "Groq says there are too many requests", False),
])
def test_errors_are_explained(service, kind, status, message, expected, needs_key):
    service.script.append(error(status, message, as_list=(kind == "gemini")))
    convo = Conversation()
    with pytest.raises(AskError) as caught:
        ask(client(service, kind=kind), convo)
    assert expected in str(caught.value)
    assert caught.value.needs_key is needs_key
    assert convo.messages == []


def test_ollama_not_running():
    with socket.socket() as s:  # find a port nobody listens on
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    c = CompatClient(Settings(ollama_url=f"http://127.0.0.1:{port}/v1"), "ollama")
    with pytest.raises(AskError) as caught:
        c.ask(Conversation(), "hi", lambda _t: None)
    assert "Ollama is not running" in str(caught.value)


def test_problem_reported_inside_the_stream(service):
    service.script.append([{"error": {"message": "quota exceeded"}}])
    with pytest.raises(AskError) as caught:
        ask(client(service), Conversation())
    assert "quota exceeded" in str(caught.value)


def test_stop_button(service):
    service.event_delay = 0.03
    service.script.append(chunks([f"part{i} " for i in range(40)]))
    convo = Conversation()
    pieces = []
    result = client(service).ask(convo, "hi", pieces.append, should_stop=lambda: len(pieces) >= 2)
    assert result.cancelled and len(pieces) == 2 and convo.messages == []


def test_missing_address_or_model():
    c = CompatClient(Settings(custom_url="", custom_model=""), "custom")
    with pytest.raises(AskError) as caught:
        c.ask(Conversation(), "hi", lambda _t: None)
    assert "address is missing" in str(caught.value)
