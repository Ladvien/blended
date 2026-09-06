"""The user's photo, on the wire: what the writer is actually shown.

A reference photo is not a render, and the two must never look alike to
the writer — a photograph read as feedback on the scene makes the writer
"fix" an object it has not built yet. So the shape of the user message
is pinned here rather than left to the UI: the lead-in that says what
the pixels are, one `[img]` per picture (adjacent same-size bitmaps
merge into video frames on the qwen-vl family — see
`test_vision_transport`), and, on a text-only writer, the eye's
description under its own header.

Interception is at `_request`, the HTTP boundary, because the eye builds
its own client with its own model: the payload on the wire is the only
honest place to assert what each model will be shown.
"""

import base64
from pathlib import Path

import pytest

from blended.agent.loop import (
    REFERENCE_PHOTO_LEAD_IN,
    REFERENCE_PHOTO_READ_PROMPT,
    AgentSession,
    ModelConfig,
    OllamaClient,
)

PHOTO_BYTES = b"png-bytes-of-a-three-legged-stool"
SYSTEM_MESSAGE = {"role": "system", "content": "system prompt"}
EYE_MODEL = "eye-model"
EYE_DESCRIPTION = "A stool with three splayed legs."


@pytest.fixture
def sent_payloads(monkeypatch):
    """Every payload these turns would have put on the wire, in order."""
    payloads: list[dict] = []

    def capture(self, path, payload, timeout_seconds):
        payloads.append(payload)
        content = EYE_DESCRIPTION if payload["model"] == EYE_MODEL else "built it"
        return {"message": {"role": "assistant", "content": content}}

    monkeypatch.setattr(OllamaClient, "_request", capture)
    return payloads


@pytest.fixture
def photo(tmp_path) -> Path:
    path = tmp_path / "stool.png"
    path.write_bytes(PHOTO_BYTES)
    return path


def _session(tmp_path: Path, vision_model: str) -> AgentSession:
    client = OllamaClient(
        ModelConfig.from_environment(model="writer", vision_model=vision_model)
    )
    return AgentSession(
        client=client,
        output_directory=tmp_path / "renders",
        messages=[dict(SYSTEM_MESSAGE)],
    )


def _wire_messages(payload: dict) -> list[dict]:
    return payload["messages"]


def test_a_vision_writer_is_shown_the_photo_itself(tmp_path, sent_payloads, photo):
    """No eye configured: the writer's own message carries the pixels."""
    session = _session(tmp_path, vision_model="")

    session.send("Build this.", reference_images=(photo,))

    assert len(sent_payloads) == 1, "a writer that can see must not call an eye"
    user_messages = [
        message
        for message in _wire_messages(sent_payloads[0])
        if message["role"] == "user"
    ]
    assert len(user_messages) == 1
    assert user_messages[0]["images"] == [
        base64.b64encode(PHOTO_BYTES).decode("ascii")
    ]
    assert user_messages[0]["content"].count("[img]") == 1
    assert REFERENCE_PHOTO_LEAD_IN in user_messages[0]["content"]
    assert "Build this." in user_messages[0]["content"]


def test_the_photo_precedes_the_reply_in_the_history(tmp_path, sent_payloads, photo):
    session = _session(tmp_path, vision_model="")

    session.send("Build this.", reference_images=(photo,))

    roles = [message["role"] for message in session.messages]
    assert roles.index("user") < roles.index("assistant")


def test_a_text_only_writer_reads_the_eyes_description(
    tmp_path, sent_payloads, photo
):
    """Two calls: the eye sees pixels, the writer sees prose."""
    session = _session(tmp_path, vision_model=EYE_MODEL)

    session.send("Build this.", reference_images=(photo,))

    eye_payload, writer_payload = sent_payloads
    eye_message = _wire_messages(eye_payload)[0]
    assert eye_payload["model"] == EYE_MODEL
    assert eye_message["images"] == [base64.b64encode(PHOTO_BYTES).decode("ascii")]
    assert REFERENCE_PHOTO_READ_PROMPT in eye_message["content"]

    user_message = next(
        message
        for message in _wire_messages(writer_payload)
        if message["role"] == "user"
    )
    assert "images" not in user_message, "a blind writer must not be sent base64"
    assert f"--- what the reference photo shows ({EYE_MODEL}) ---" in (
        user_message["content"]
    )
    assert EYE_DESCRIPTION in user_message["content"]


def test_the_eye_is_asked_about_the_photo_not_about_a_render(
    tmp_path, sent_payloads, photo
):
    """The render prompt asks "does it read as the intended thing?" —
    meaningless for a photograph, where the photo IS the intent."""
    session = _session(tmp_path, vision_model=EYE_MODEL)

    session.send("Build this.", reference_images=(photo,))

    eye_content = _wire_messages(sent_payloads[0])[0]["content"]
    assert "has just rendered it" not in eye_content


def test_the_reference_events_come_before_the_eyes_words(
    tmp_path, sent_payloads, photo
):
    """The panel pairs a picture with what was said about it."""
    session = _session(tmp_path, vision_model=EYE_MODEL)
    events: list[tuple[str, str]] = []

    session.send(
        "Build this.",
        on_event=lambda kind, text: events.append((kind, text)),
        reference_images=(photo,),
    )

    kinds = [kind for kind, _ in events]
    assert ("reference", str(photo)) in events
    assert kinds.index("reference") < kinds.index("vision")


def test_the_photo_is_not_re_sent_on_the_next_turn(tmp_path, sent_payloads, photo):
    """It rides the history, so refinement turns still see it — and a
    second copy would be billed again as new image tokens."""
    session = _session(tmp_path, vision_model="")

    session.send("Build this.", reference_images=(photo,))
    session.send("Now make the legs thinner.")

    last_turn = _wire_messages(sent_payloads[-1])
    carrying_images = [message for message in last_turn if message.get("images")]
    assert len(carrying_images) == 1


def test_a_turn_without_a_photo_is_untouched(tmp_path, sent_payloads):
    session = _session(tmp_path, vision_model="")

    session.send("Build a crate.")

    user_message = next(
        message
        for message in _wire_messages(sent_payloads[0])
        if message["role"] == "user"
    )
    assert user_message == {"role": "user", "content": "Build a crate."}
