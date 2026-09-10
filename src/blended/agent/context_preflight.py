"""Refuse to send what will not fit; refuse to read what was cut (OT-22).

The one place the fail-loud rule was missing: a transport whose model
context is smaller than the prompt plus the tool set would truncate
(Ollama silently, llama.cpp with a flag nobody read), and a completion
cut at `max_tokens` came back as a reply. Measured 2026-09-10: 16,814
static tokens per call on the OpenAI/Ollama lanes before any history,
against a 32,768 `num_ctx` on the Ollama lane and 65,536 on bmb.

Sizes before sending are an ESTIMATE, and say so: characters divided by
`CHARS_PER_TOKEN_ESTIMATE`, the ratio measured with bmb's tokenizer on
the assembled prompt (29,064 / 7,569 = 3.84) and on the tools JSON
(35,147 / 9,245 = 3.80). The reply's `usage` is the exact count and is
checked after the fact.

Pure: numbers and dicts; the lane's context comes in as a value.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

CHARS_PER_TOKEN_ESTIMATE = 3.8
# The reply's own signals that it was cut, per wire protocol.
OPENAI_LENGTH_FINISH = "length"
OLLAMA_LENGTH_DONE = "length"


class ContextExceeded(RuntimeError):
    """The request would not fit the lane's context, or the server cut the prompt."""


class ReplyTruncated(RuntimeError):
    """The model's reply stopped at the completion ceiling: it is not an answer."""


@dataclass(frozen=True)
class PreflightReport:
    checked: bool
    estimated_prompt_tokens: int
    context_tokens: int | None
    reason: str = ""


def estimate_tokens(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN_ESTIMATE) + 1


def estimate_request_tokens(messages: list[dict], tools: list[dict] | None) -> int:
    """What the wire will carry, estimated: the messages and the tool set as JSON."""
    return estimate_tokens(json.dumps(messages)) + (estimate_tokens(json.dumps(tools)) if tools else 0)


def preflight(
    messages: list[dict],
    tools: list[dict] | None,
    context_tokens: int | None,
    reserved_completion_tokens: int,
    lane: str,
) -> PreflightReport:
    """Raise ContextExceeded naming every number when the request cannot fit.

    A lane whose context is not known (no entry for its model) is not
    checked — and the report says so, so the caller can say so too.
    """
    estimated = estimate_request_tokens(messages, tools)
    if context_tokens is None:
        return PreflightReport(False, estimated, None, f"no measured context for this model on {lane}")
    if estimated + reserved_completion_tokens > context_tokens:
        raise ContextExceeded(
            f"refusing to send on {lane}: estimated prompt {estimated:,} tokens "
            f"(chars / {CHARS_PER_TOKEN_ESTIMATE}) + reserved completion "
            f"{reserved_completion_tokens:,} = {estimated + reserved_completion_tokens:,} "
            f"> context {context_tokens:,}. The transport would truncate silently; "
            f"narrow the task or shorten the history."
        )
    return PreflightReport(True, estimated, context_tokens)


def check_reply_fits(body: dict, context_tokens: int | None, lane: str) -> None:
    """Raise on a reply the model or the server cut short.

    OpenAI protocol: `choices[0].finish_reason == "length"`, a
    `truncated` flag (llama.cpp), or `usage.prompt_tokens` above the
    context. Ollama: `done_reason == "length"`. Streamed replies carry
    the same fields on the assembled message dict.
    """
    choice = (body.get("choices") or [{}])[0]
    finish = choice.get("finish_reason") or body.get("finish_reason")
    if finish == OPENAI_LENGTH_FINISH:
        raise ReplyTruncated(
            f"{lane} stopped the reply at the completion ceiling (finish_reason=length); "
            f"the text is cut, not an answer. Raise max_completion_tokens or narrow the task."
        )
    if body.get("done_reason") == OLLAMA_LENGTH_DONE:
        raise ReplyTruncated(f"{lane} stopped the reply at the completion ceiling (done_reason=length).")
    if body.get("truncated"):
        raise ContextExceeded(f"{lane} truncated the PROMPT to fit its context (truncated=true).")
    usage = body.get("usage") or {}
    prompt_tokens = int(usage.get("prompt_tokens") or body.get("prompt_eval_count") or 0)
    if context_tokens is not None and prompt_tokens > context_tokens:
        raise ContextExceeded(
            f"{lane} reports {prompt_tokens:,} prompt tokens against a context of "
            f"{context_tokens:,}: the server cut the prompt."
        )
