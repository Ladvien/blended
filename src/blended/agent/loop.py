"""The conversational agent loop, over an Ollama- or OpenAI-compatible
endpoint.

Zero third-party dependencies — Blender's bundled Python has no pip
packages, and an addon that needs `pip install` inside Blender is an
addon nobody runs. Everything here uses `urllib` from the stdlib.

Model choice is CONFIGURATION, not code. `ModelConfig` carries the
model name and the endpoint, and the same loop runs against a local
Ollama, Ollama Cloud, llama-swap on bmb (OpenAI protocol), or anything
speaking the Ollama or OpenAI chat APIs. See `RECOMMENDED_MODELS` for
the reasoning behind the defaults.
"""

from __future__ import annotations

import base64
import json
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from blended.agent.claude_code import (
    CLAUDE_CODE_DEFAULT_EFFORT,
    CLAUDE_CODE_ENDPOINT,
    CLAUDE_CODE_REQUEST_TIMEOUT_SECONDS,
    IMAGE_PLACEHOLDER_TOKEN,
    ClaudeCodeTransport,
    TurnCost,
    is_claude_code_model,
)
from blended.agent.context_preflight import ContextExceeded, check_reply_fits, preflight
from blended.agent.intermediates import IntermediateLedger
from blended.agent.outcome import ToolOutcome
from blended.agent.plan import (
    MISSING_PLAN_REFUSAL,
    PLAN_TOOL_NAME,
    TurnPlan,
    encode_plan_event,
    parse_plan_arguments,
    plan_required_for,
    plan_step_of,
)
from blended.agent.tool_disclosure import offered_fingerprint
from blended.agent.tool_event import TOOL_EVENT_KIND, ToolEvent, encode_tool_event
from blended.stages import STAGE_DONE

LOCAL_ENDPOINT = "http://localhost:11434"
CLOUD_ENDPOINT = "https://ollama.com"
CHAT_PATH = "/api/chat"
TAGS_PATH = "/api/tags"
OPENAI_CHAT_PATH = "/v1/chat/completions"
# llama-swap on bmb speaks the OpenAI protocol; bmb exposes the port
# directly on the LAN at this address (no SSH tunnel needed).
BMB_ENDPOINT = "http://192.168.1.233:9292"
# `big` runs llama-swap on the LAN holding the local vision weights
# (this machine's daemon is a signed-in cloud proxy with no models
# pulled). OpenAI protocol, NO auth: /v1/models answers 200 with and
# without a bearer, because that llama-swap has no apiKeys list
# (verified live 2026-09-03). The served id is `qwen3-vl` =
# Qwen3-VL-8B-Instruct Q8_0 + mmproj-F16 at -c 16384, ttl 600.
# STRICT SWAP: one model resident at a time on that 24 GB card, which
# is why the local WRITER stays on bmb — a 22 GiB qwen3.8-27b on big
# would evict the eye on every alternation.
BIG_ENDPOINT = "http://192.168.1.110:8081"
REQUEST_TIMEOUT_SECONDS = 300
# A local llama-swap lane gets a longer ceiling than the cloud lanes.
# Not a guess: bmb's qwen3.8-27b (Q8_XL, --reasoning-format deepseek)
# answered the FIRST turn of the planter_box brief — 6239 prompt
# tokens of system prompt plus 6 tool schemas — in 353.7 s with 3880
# completion tokens, almost all of them thinking, and returned a
# well-formed tool call. Against the 300 s cloud ceiling that turn
# died mid-generation with `TimeoutError: timed out` (measured twice,
# 2026-09-03), so `make converge-local` could never reach its first
# tool call. Cloud writers answer the same turn in well under 60 s and
# keep the tight ceiling, so a dead cloud endpoint is still reported
# rather than waited on.
# Derived, not guessed (OT-22). One full-prefix request on bmb's
# qwen3.8-27b, measured 2026-09-10: cold prefill 142.9 s for 16,997
# prompt tokens (119 tok/s) and generation at 10.5 tok/s (711 tokens in
# 67.7 s); the same request warm read its prefix from llama-server's
# cache in 0.3 s. A ceiling has to hold the worst legal call: a cold
# model load (~240 s), the cold prefill, and a completion that runs to
# max_completion_tokens — 16,384 / 10.5 = 1,560 s — so 240 + 143 + 1,560
# ~= 1,943 s. The previous 900 s was measured on a 353.7 s first turn
# and killed OT-10's first instance mid-generation.
LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS = 2000

# The context each served model actually has, for the preflight (OT-22).
# Read from the servers' own configs, never assumed: bmb
# ~/llm/llama-swap.yaml `-c` per model, read 2026-09-10. A model with no
# entry cannot be preflighted and `ModelConfig.context_tokens` says so
# (None); the loop reports it rather than guess.
CONTEXT_TOKENS_BY_MODEL = {
    "qwen3.8-27b": 65_536,
    "qwen3.8-27b-q4xl": 65_536,
    "gpt-oss-20b": 65_536,
    "qwen3-32b": 32_768,
    "hermes-4-14b": 32_768,
    "gemma-4-26b-a4b": 32_768,
    "glm-ocr": 32_768,
}
# The CLI lane's models: Anthropic's documented 200k context for the
# Claude models the CLI serves (docs.anthropic.com, model overview).
CLAUDE_CODE_CONTEXT_TOKENS = 200_000
# The preflight sends a real one-token chat, so it pays whatever the
# model's cold start costs. Measured 2026-08-22: a cloud model proxied
# through a local daemon answered `ping` in 23.3 s from cold, against a
# 10 s preflight — so the harness refused to score a run on a backend
# that was working. Generous relative to a cold start, still far short
# of REQUEST_TIMEOUT_SECONDS, so a genuinely dead endpoint is reported
# rather than waited on.
PREFLIGHT_TIMEOUT_SECONDS = 90
# What a stopped turn says, to the user and to the model's history.
CANCELLED_ANSWER = "Stopped at your request. The scene is as the last tool call left it."
CANCELLED_TOOL_RESULT = "Not executed: the user stopped this turn."

API_KEY_ENVIRONMENT_VARIABLE = "OLLAMA_API_KEY"
HOST_ENVIRONMENT_VARIABLE = "OLLAMA_HOST"
# Where the bmb llama-swap key lives on THIS machine (written from
# bmb's llama-swap.yaml, chmod 0600). Finder-launched Blender has no
# shell environment, so the key must come from a file, not an export.
BMB_API_KEY_FILE = Path.home() / ".blended" / "bmb_api_key"


def _read_bmb_api_key() -> str:
    """The bmb llama-swap key, or "" when the file is absent.

    Absent is fine — the addon preference or a manually created file
    can supply it. An unreadable or malformed file FAILS LOUDLY (raises)
    rather than silently sending an empty key and 401ing.
    """
    if not BMB_API_KEY_FILE.exists():
        return ""
    key = BMB_API_KEY_FILE.read_text(encoding="utf-8").strip()
    if len(key) != 64 or not all(c in "0123456789abcdef" for c in key):
        raise RuntimeError(
            f"{BMB_API_KEY_FILE} does not hold a 64-hex llama-swap key "
            f"(got {len(key)} chars). Fix or remove the file."
        )
    return key


# OpenRouter: one OpenAI-protocol gateway over many vendors' models.
# Ids are `vendor/model` (e.g. `qwen/qwen3-vl-8b-instruct`), which is
# the discriminator below — no Ollama id (`name:tag`) and no llama-swap
# id served here carries a slash. Metered per token on a small prepaid
# balance ($20, 2026-09-04), so this lane is for the provider smoke and
# deliberate opt-in, never for bench or E2E sweeps.
# The base WITHOUT /v1: the client appends OPENAI_CHAT_PATH, and
# .../api/v1/v1/chat/completions 404s with an HTML page.
OPENROUTER_ENDPOINT = "https://openrouter.ai/api"
OPENROUTER_API_KEY_FILE = Path.home() / ".blended" / "openrouter_api_key"
OPENROUTER_API_KEY_PREFIX = "sk-or-"
# OpenRouter attributes usage to an app through these two headers; they
# are optional on the wire and show up on the dashboard.
OPENROUTER_APP_HEADERS = {
    "HTTP-Referer": "https://github.com/ladvien/blended",
    "X-Title": "blended",
}


def _read_openrouter_api_key() -> str:
    """The OpenRouter key from its file, or "" when the file is absent.

    The file holds either the bare key or a shell-style
    `OPENROUTER_API_KEY=sk-or-...` line (how it was first written), so
    both forms are accepted. Anything else fails loudly: a key that is
    not `sk-or-*` would 401 every call with no clue why.
    """
    if not OPENROUTER_API_KEY_FILE.exists():
        return ""
    key = OPENROUTER_API_KEY_FILE.read_text(encoding="utf-8").strip()
    _, _, after_equals = key.rpartition("=")
    key = after_equals.strip() or key
    if not key.startswith(OPENROUTER_API_KEY_PREFIX):
        raise RuntimeError(
            f"{OPENROUTER_API_KEY_FILE} does not hold an OpenRouter key "
            f"(expected it to start with {OPENROUTER_API_KEY_PREFIX!r}). "
            f"Fix or remove the file."
        )
    return key


def _is_openrouter_model(model: str) -> bool:
    """`vendor/model` ids belong to OpenRouter; nothing else has a slash."""
    return "/" in model

# Why these, given what this harness actually asks of a model.
#
# The job is: write bpy Python, call tools, read measured gate reports,
# and LOOK at contact sheets. The analyzer is the hard gate, so vision
# is advisory — but a stronger VLM still catches wrong-object failures
# the gate cannot (measured here: a planter that passed every
# structural check with its drainage hole sealed shut).
#
# BILLING MATTERS. Ollama Cloud splits two ways, and the model pages
# show which is which:
#   * a usage-level label (Low/Medium/High Usage) -> covered by the
#     subscription, drawing on session and weekly limits
#   * per-token dollar pricing -> metered, billed on top
# kimi-k3 is the strongest VLM on the platform but is METERED at
# $3/$15 per 1M tokens. Everything defaulted to below is
# subscription-covered.
RECOMMENDED_MODELS = {
    "writer": (
        "claude-code:sonnet",
        (
            "Drives every turn: writes bpy, calls tools, reads gate "
            "reports, and — being natively multimodal — LOOKS at its own "
            "renders, so no prose summary sits between the picture and "
            "the code. Default writer. Qualified on the five-brief suite "
            "at the pinned prompt on 2026-09-05 (iterations 52-56): "
            "structural, form and refinement gates green on 5/5 briefs, "
            "first attempt, zero failures, a plan declared before the "
            "first edit in every run. The visual gate reports drift for "
            "this writer BY CONSTRUCTION — the golden renders were "
            "minted from deepseek-v4-pro's runs, so another writer's "
            "legitimate solution moves the render (the stool at "
            "iteration 55 is a well-formed three-legged stool that is "
            "simply not deepseek's stool). Subscription-covered through "
            "the signed-in CLI; rate-limited by the 5h/7d windows."
        ),
    ),
    "writer_scored_cloud": (
        "deepseek-v4-pro:cloud",
        (
            "1.65T MoE, and the writer that MINTED the golden references "
            "the visual gate and the examiner compare against "
            "(iterations 47-51, revision 10) — which is why it stays "
            "offered and why `CONVERGENCE_WRITER_MODEL` still names it. "
            "Pick it to reproduce a scored run exactly, or when the CLI "
            "lane is outside its subscription window. "
            "deepseek-v4-flash is deliberately absent: it was scored "
            "through v1-v4 and never converged this suite — the last two "
            "blockers were not prompt wording but a writer too weak to "
            "place geometry (see the v5 pin comment in prompt_versions)."
        ),
    ),
    "eye": (
        "claude-code:sonnet",
        (
            "The writer's OWN model, which is why it is the default: an "
            "eye equal to the writer means `uses_separate_eye` is False, "
            "so a render reaches the writer as a native image block "
            "instead of a prose summary — no second call, and nothing "
            "lost in between (RESP measures the reference-paired path at "
            "recall 0.76 against 0.28 for no reference, "
            "10.48550/arXiv.2604.11082). Licensed on the fixture zoo "
            "2026-09-05: sensitivity 0.80 (4/5), control specificity "
            "1.00 (5/5). Measured the same day: two renders arrive "
            "unfused and in order — swapping them swaps the answer."
        ),
    ),
    "eye_licensed_cloud": (
        "kimi-k2.7-code:cloud",
        (
            "The superseded default, still licensed by its own recorded "
            "calibration (_evaluate/eye_calibration_kimi.json): "
            "sensitivity 0.80, control specificity 1.00, measured "
            "2026-08-24. Its miss is COMPLEMENTARY to claude-code's — it "
            "missed lid_offset and saw floating_seat. Pick it when the "
            "writer is not vision-capable and the CLI lane is out of "
            "subscription window. minimax-m3:cloud was the old default "
            "but is broken on this harness: it answers in "
            "message.thinking and returns empty content (measured "
            "2026-08-24), so every examiner call would fail the JSON "
            "contract."
        ),
    ),
    "single_model_subscription": (
        "kimi-k2.7-code:cloud",
        (
            "Vision + coding-tuned, so it can drive everything itself. "
            "minimax-m3:cloud used to hold this slot but returns empty "
            "content (thinking trap) — see the eye entry."
        ),
    ),
    "single_model_fast": (
        "kimi-k2.7-code:cloud",
        (
            "High Usage tier, vision + coding-tuned, ~30% fewer thinking "
            "tokens. Good one-model compromise."
        ),
    ),
    "best_overall_metered": (
        "kimi-k3:cloud",
        (
            "2.81T params, text/image/video, 1M context — the strongest VLM "
            "available. NOT subscription-covered: $3/$15 per 1M tokens, "
            "billed separately. Opt in deliberately."
        ),
    ),
    # bmb's llama-swap (OpenAI protocol at BMB_ENDPOINT, exposed
    # directly on the LAN). These ids are EXACTLY what bmb's /v1/models
    # serves — a dropdown id that is not in this tuple has no server,
    # which is how gpt-oss-20b-heretic:latest 404'd (nothing anywhere
    # serves it; the real served id is gpt-oss-20b).
    "local_writer_bmb": (
        "qwen3.8-27b",
        (
            "bmb llama-swap (OpenAI protocol via "
            f"{BMB_ENDPOINT}, exposed directly on the LAN). Local "
            "and free; no subscription usage. Pair it with `qwen3-vl` "
            "on big for a fully-local run (`make converge-local`). "
            "The id is exactly what /v1/models serves."
        ),
    ),
    "local_eye_big": (
        "qwen3-vl",
        (
            "Qwen3-VL-8B-Instruct Q8_0 + F16 projector on big's "
            f"llama-swap ({BIG_ENDPOINT}), OpenAI wire, no key. The "
            "local half of the fully-local pair: writer qwen3.8-27b on "
            "bmb, eye qwen3-vl on big — two hosts, so neither evicts "
            "the other. Measured 2026-09-03: 258 prompt tokens per "
            "512x512 render (the Ollama lane cost ~1050), 1160 for a "
            "1048x1048 contact sheet, multiple images delivered "
            "unfused and in order. DESCRIBE-only: the licensed "
            "examiner slot holds kimi's calibration, so machine "
            "verdicts still need --examiner none."
        ),
    ),
    # The headless Claude Code CLI (see agent/claude_code.py). No key,
    # no endpoint, no metered balance: the binary owns its own auth and
    # this harness never handles the token. One transport serves both
    # slots because the model is natively multimodal — measured
    # 2026-09-05: renders arrive as real image blocks (1315 prompt
    # tokens with none, 1685 with one, 2068 with two, unfused and in
    # order), so a `claude-code:` writer can be its OWN eye with
    # `vision_model` left empty.
    "claude_code_writer": (
        "claude-code:sonnet",
        (
            "Claude Code in headless mode, subscription-covered through "
            "the signed-in CLI. Tool calls are schema-CONSTRAINED via "
            "--json-schema rather than parsed out of prose. Rate-limited "
            "by the 5h/7d subscription windows, not metered; overage on "
            "this account is rejected, so a window hit is a hard stop "
            "the preflight and the panel report."
        ),
    ),
    "claude_code_eye": (
        "claude-code:haiku",
        (
            "The cheapest Claude Code model for the eye slot: it only "
            "describes renders, and the same subscription covers it. "
            "Pick `claude-code:sonnet` for both slots when the writer "
            "should look at its own renders instead."
        ),
    ),
}
# Every model bmb's llama-swap serves, per its /v1/models (verified
# against the live endpoint 2026-08-23).
BMB_MODEL_IDS = (
    "gemma-4-26b-a4b",
    "glm-ocr",
    "gpt-oss-20b",
    "hermes-4-14b",
    "qwen3-32b",
    "qwen3.8-27b",
)
# Every model `big`'s llama-swap serves that this addon offers, per its
# /v1/models (verified live 2026-09-03). The local eye lives THERE, not
# on this machine: mac_air's daemon reports zero models, so routing
# qwen3-vl to LOCAL_ENDPOINT 404s with "model not found".
BIG_MODEL_IDS = ("qwen3-vl",)
# Every endpoint that speaks OpenAI /v1/chat/completions instead of
# Ollama /api/chat: the two LAN llama-swaps and OpenRouter. The cloud
# and the local daemon are Ollama.
LLAMA_SWAP_ENDPOINTS = (BMB_ENDPOINT, BIG_ENDPOINT)
OPENAI_PROTOCOL_ENDPOINTS = (*LLAMA_SWAP_ENDPOINTS, OPENROUTER_ENDPOINT)
# Every endpoint that serves ONLY its own model ids, so an eye with no
# server of its own cannot inherit it: the two llama-swaps, OpenRouter,
# and the Claude Code CLI. The local daemon is the fallback because it
# is the one endpoint that serves whatever it is signed in for.
MODEL_IMPLIED_ENDPOINTS = (*OPENAI_PROTOCOL_ENDPOINTS, CLAUDE_CODE_ENDPOINT)


def _implied_endpoint(model: str) -> str:
    """The one server that serves `model`, ignoring explicit overrides.

    A model id implies its host: a `claude-code:` id is the local
    headless CLI, bmb's llama-swap serves BMB_MODEL_IDS, big's
    llama-swap serves BIG_MODEL_IDS, a `vendor/model` id is
    OpenRouter's, everything else rides the local daemon (which proxies
    cloud models once `ollama signin` ran). One table, used by both
    writer and eye resolution — a model id absent from every table has
    no server, and that is what a 404 means.
    """
    if is_claude_code_model(model):
        return CLAUDE_CODE_ENDPOINT
    if model in BMB_MODEL_IDS:
        return BMB_ENDPOINT
    if model in BIG_MODEL_IDS:
        return BIG_ENDPOINT
    if _is_openrouter_model(model):
        return OPENROUTER_ENDPOINT
    return LOCAL_ENDPOINT


def _implied_api_key(model: str, environment_key: str) -> str:
    """The credential `model`'s own server wants.

    bmb's llama-swap 401s without its key file; big's llama-swap has no
    apiKeys list and must never be handed a cloud key; OpenRouter takes
    its own key file; the Claude Code CLI owns its own auth and this
    harness never handles its token; everything else rides the Ollama
    lanes, where the env key (or a signed-in daemon) is the credential.
    Used by BOTH writer and eye resolution so the eye cannot inherit a
    credential for a server it is not talking to.
    """
    endpoint = _implied_endpoint(model)
    if endpoint == BMB_ENDPOINT:
        return _read_bmb_api_key()
    if endpoint in (BIG_ENDPOINT, CLAUDE_CODE_ENDPOINT):
        return ""
    if endpoint == OPENROUTER_ENDPOINT:
        return _read_openrouter_api_key()
    return environment_key


# What the eye is asked when a tool hands back a render. It describes;
# it does not adjudicate. The analyzer already returned a hard verdict on
# structure, and the measured failure mode of VLM critics is a bias
# toward accepting — so asking one to "check if this is correct" invites
# a rubber stamp. Asking it to REPORT lets the writer do the judging.
VISION_DESCRIBE_PROMPT = """\
You are the eyes for another agent that cannot see. It is building a 3D
game asset in Blender and has just rendered it.

Describe what is actually in these views, concretely and literally:
- What object does this appear to be? Does it read as the intended thing?
- Proportions: anything too thick, thin, tall, short, or misplaced?
- Parts: are the expected pieces present, and positioned sensibly?
- Anything visibly wrong, missing, floating, intersecting, or duplicated?

Report what you SEE. Do not say whether it passes or fails — a separate
analyzer already measured the geometry. Do not speculate about topology,
normals, or manifoldness; you cannot see those. If something looks
right, say so plainly rather than inventing problems.

Be specific and brief: 3-6 sentences."""


# Headers under which an eye's description is appended to the message
# that carried the pictures. Two, because the writer must never confuse
# a photograph of the real object with a render of its own work.
RENDER_IMAGE_HEADER = "what the render shows"
REFERENCE_IMAGE_HEADER = "what the reference photo shows"
# What the writer is told the attached pixels ARE. Without this a photo
# arrives looking exactly like the harness's own render, and the writer
# reads it as feedback on a scene it has not built yet.
REFERENCE_PHOTO_LEAD_IN = (
    "Reference photo of the object to build — the user's own picture of a "
    "real object, not a render of the scene:"
)
# What the eye is asked when the picture is the user's, not ours. The
# render prompt above asks "does it read as the intended thing?", which
# is meaningless for a photograph: here the photo IS the intent, so the
# eye is asked for the things a modeller needs — silhouette, parts,
# attachment, ratios, up-axis, symmetry — and explicitly not for
# colour, lighting or background, none of which the writer models.
REFERENCE_PHOTO_READ_PROMPT = """\
You are the eyes for another agent that cannot see. It must model the
object in this photograph in Blender.

Report only what is visible:
- What the object is, and its overall silhouette.
- The parts it is made of, and how they attach.
- Proportions as ratios of the whole (e.g. "the legs are about two
  thirds of the total height"), not absolute sizes.
- Which way is up in the picture, and whether the object is symmetric.
- Surface features that change the geometry: bevels, ribs, holes,
  handles, cutouts.

Do not guess a real-world size unless a familiar object gives the scale;
say so if nothing does. Do not describe colour, lighting, or background.
Be concrete and complete: 8-14 short lines."""
# What the writer is told when the eye cannot be reached at all. One
# constant, both call sites: a turn where the eye is down must say so in
# the history the writer reads, or the writer silently invents detail.
EYE_UNREACHABLE_NOTE = (
    "(The vision model could not be reached: {error}. You are working "
    "blind on this image — rely on the gate report and ask the user to "
    "look.)"
)


@dataclass(frozen=True)
class ModelConfig:
    model: str = RECOMMENDED_MODELS["writer"][0]
    # The eye. Set to "" to make the writer handle images itself, which
    # only works if the writer is vision-capable — deepseek-v4-flash is
    # not, so leaving this empty with the default writer means renders
    # are never actually looked at.
    vision_model: str = RECOMMENDED_MODELS["eye"][0]
    endpoint: str = LOCAL_ENDPOINT
    temperature: float = 0.3  # low: this is engineering, not brainstorming
    context_length: int = 32768
    api_key: str = ""
    # Completion ceiling on the OpenAI-protocol lanes. The bmb writer is
    # a REASONING build: its 65536-token context and thinking budget
    # make 4096 a starvation cap — measured live 2026-08-23: the tool
    # round trip returned EMPTY content with finish_reason=length, then
    # answered in 72 tokens with 16384. A metered lane (OpenRouter) can
    # lower this per call to bound spend.
    max_completion_tokens: int = 16384
    # Claude Code lane only. The effort level is passed explicitly so a
    # harness run does not change behaviour when the user edits their
    # own settings.json; the binary path exists because Blender launched
    # from Finder inherits no shell PATH.
    claude_code_effort: str = CLAUDE_CODE_DEFAULT_EFFORT
    claude_code_binary_path: str = ""

    @classmethod
    def from_environment(
        cls,
        model: str = "",
        endpoint: str = "",
        api_key: str = "",
        **overrides,
    ) -> ModelConfig:
        """Resolve endpoint and auth.

        The model implies its server when nothing explicit was given
        (`_implied_endpoint`): qwen3.8 is bmb's llama-swap, qwen3-vl is
        big's daemon, everything else rides the local daemon (which
        proxies cloud models once `ollama signin` has
        authenticated it). An explicit non-default endpoint or
        OLLAMA_HOST wins over the model's implied server — but the
        default `http://localhost:11434` is treated as UNSET, because
        it is what every fresh install and every saved preference holds,
        and it must not override the model the user just picked.

        The daemon-first path also sidesteps a real macOS trap: Blender
        launched from Finder does NOT inherit your shell environment, so
        OLLAMA_API_KEY is invisible to it even though
        `echo $OLLAMA_API_KEY` works fine in a terminal.
        """
        import os

        resolved_model = model or RECOMMENDED_MODELS["writer"][0]
        # Auth order, one path per lane:
        #   * an explicit api_key (addon preference) always wins;
        #   * otherwise the credential follows the SERVER the model id
        #     implies: a bmb model reads the bmb key file
        #     (~/.blended/bmb_api_key, 0600, written from bmb's
        #     llama-swap.yaml) — Finder-launched Blender has no shell
        #     environment, so the key must come from a file, not an
        #     export; big's llama-swap takes NO key; every other lane
        #     falls back to OLLAMA_API_KEY.
        # The Ollama env key is deliberately NOT sent to either
        # llama-swap: it is the wrong credential there and would 401.
        resolved_key = api_key
        if not resolved_key:
            resolved_key = _implied_api_key(
                resolved_model, os.environ.get(API_KEY_ENVIRONMENT_VARIABLE, "")
            )
        explicit_endpoint = (
            endpoint if endpoint and endpoint != LOCAL_ENDPOINT else ""
        )
        resolved_endpoint = (
            explicit_endpoint
            or os.environ.get(HOST_ENVIRONMENT_VARIABLE, "")
            or _implied_endpoint(resolved_model)
        )
        return cls(
            model=resolved_model,
            endpoint=resolved_endpoint,
            api_key=resolved_key,
            **overrides,
        )

    def with_endpoint(self, endpoint: str) -> ModelConfig:
        from dataclasses import replace

        return replace(self, endpoint=endpoint)

    @property
    def is_cloud_endpoint(self) -> bool:
        return CLOUD_ENDPOINT in self.endpoint

    @property
    def uses_openai_protocol(self) -> bool:
        """llama-swap on bmb and big, and OpenRouter; the Ollama lanes are the rest."""
        return any(host in self.endpoint for host in OPENAI_PROTOCOL_ENDPOINTS)

    @property
    def is_openrouter(self) -> bool:
        return OPENROUTER_ENDPOINT in self.endpoint

    @property
    def uses_claude_code(self) -> bool:
        """True when this config's turns run through the headless CLI."""
        return self.endpoint == CLAUDE_CODE_ENDPOINT

    @property
    def request_timeout_seconds(self) -> int:
        """The per-call ceiling this lane's server actually needs.

        A ceiling, not a wait: the LAN llama-swap lanes hold a local 27B
        thinking model whose first turn was measured at 353.7 s, so the
        cloud ceiling killed it mid-generation. OpenRouter is a cloud
        lane and keeps the tight ceiling so a dead gateway is reported.
        """
        if self.uses_claude_code:
            return CLAUDE_CODE_REQUEST_TIMEOUT_SECONDS
        if any(host in self.endpoint for host in LLAMA_SWAP_ENDPOINTS):
            return LLAMA_SWAP_REQUEST_TIMEOUT_SECONDS
        return REQUEST_TIMEOUT_SECONDS

    @property
    def context_tokens(self) -> int | None:
        """The lane's model context for the preflight (OT-22), or None when
        no measured number exists for this model on this lane."""
        if self.uses_claude_code:
            return CLAUDE_CODE_CONTEXT_TOKENS
        if self.uses_openai_protocol:
            return CONTEXT_TOKENS_BY_MODEL.get(self.model)
        return self.context_length  # what the Ollama request sends as num_ctx

    @property
    def uses_separate_eye(self) -> bool:
        """True when a distinct vision model handles images."""
        return bool(self.vision_model) and self.vision_model != self.model

    def eye_config(self) -> ModelConfig:
        """The config for this config's vision model.

        An eye whose model implies its own server rides that server:
        the bmb model rides bmb's OpenAI lane (the wire carries images
        there), the `qwen3-vl` eye rides big's llama-swap, a
        `claude-code:` eye rides the headless CLI. An eye with
        no implied server (a cloud model) inherits the writer's
        endpoint — unless the writer sits on a model-implied server,
        which serves only its own ids, in which case the eye falls to
        the local daemon. The credential follows the eye's server, so a
        cloud writer's key never rides to a llama-swap — and a writer
        whose lane is not Ollama (bmb file, OpenRouter file, the CLI's
        own auth) never rides its key to the daemon: the daemon lane
        only ever inherits a key the writer itself got from the Ollama
        lanes.
        """
        eye_endpoint = _implied_endpoint(self.vision_model)
        if (
            eye_endpoint == LOCAL_ENDPOINT
            and self.endpoint not in MODEL_IMPLIED_ENDPOINTS
        ):
            eye_endpoint = self.endpoint
        import os

        ollama_lane_key = (
            self.api_key
            if not self.uses_openai_protocol and not self.uses_claude_code
            else os.environ.get(API_KEY_ENVIRONMENT_VARIABLE, "")
        )
        return replace(
            self,
            model=self.vision_model,
            endpoint=eye_endpoint,
            api_key=_implied_api_key(self.vision_model, ollama_lane_key),
        )

    def describe_routing(self) -> str:
        if self.uses_separate_eye:
            return (
                f"writer={self.model} (text/tools), "
                f"eye={self.vision_model} (images only)"
            )
        return f"{self.model} handles text and images"


@dataclass(frozen=True)
class ConnectionStatus:
    ok: bool
    endpoint: str
    detail: str

    def summary(self) -> str:
        return f"{'OK' if self.ok else 'FAILED'} [{self.endpoint}] {self.detail}"


def _to_openai_messages(messages: list[dict]) -> list[dict]:
    """Convert Ollama-style message dicts to OpenAI chat message dicts.

    The common subset survives: role + content, tool results with their
    tool_call_id, and the Ollama `images` field becomes OpenAI
    image_url parts — bmb's qwen3.8 is used as the EYE too, so the
    OpenAI lane carries images, not just text. Unknown keys are dropped
    silently.
    """
    converted: list[dict] = []
    for message in messages:
        role = message.get("role", "user")
        converted_message = {"role": role}
        content = message.get("content", "")
        images = message.get("images")
        if images:
            parts: list[dict] = []
            if content:
                parts.append({"type": "text", "text": content})
            for image in images:
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image}"},
                    }
                )
            converted_message["content"] = parts
        else:
            converted_message["content"] = content
        if role == "tool" and message.get("tool_call_id"):
            converted_message["tool_call_id"] = message["tool_call_id"]
        converted.append(converted_message)
    return converted


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["function"]["name"],
                "description": tool["function"].get("description", ""),
                "parameters": tool["function"].get("parameters", {}),
            },
        }
        for tool in tools
    ]


def _assistant_message_from_openai(body: dict) -> dict:
    """OpenAI chat-completions body -> the assistant message dict the
    loop already consumes, ids preserved for the tool-result round
    trip."""
    choice = (body.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    tool_calls = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        tool_calls.append(
            {
                "id": call.get("id", ""),
                "function": {
                    "name": function.get("name", ""),
                    "arguments": function.get("arguments") or {},
                },
            }
        )
    normalized = {
        "role": message.get("role", "assistant"),
        "content": message.get("content") or "",
        "tool_calls": tool_calls,
    }
    reasoning = message.get("reasoning_content")
    if reasoning:
        normalized["thinking"] = reasoning
    return normalized


# macOS ships its trust store at this path. Blender's bundled Python and
# Homebrew's find it on their own; the python.org framework build looks
# only in its own etc/openssl, which is empty until its
# "Install Certificates" step runs — so every https lane (OpenRouter,
# ollama.com) failed CERTIFICATE_VERIFY_FAILED from the venv while
# working from Blender (measured 2026-09-04). One context, one file.
SYSTEM_CA_BUNDLE = Path("/etc/ssl/cert.pem")


def _tls_context():
    import ssl

    if ssl.get_default_verify_paths().cafile is None and SYSTEM_CA_BUNDLE.exists():
        return ssl.create_default_context(cafile=str(SYSTEM_CA_BUNDLE))
    return ssl.create_default_context()


SSE_DATA_PREFIX = "data:"
SSE_DONE_MARKER = "[DONE]"


# Streaming exists for the person watching, not the model: seeing the
# reply and the thinking arrive is how the UI "makes clear why the
# system did what it did" (Amershi et al., G11, DOI
# 10.1145/3290605.3300233) during turns that take minutes.
def _assemble_openai_stream(lines, on_delta, stop_requested) -> dict:
    """Fold OpenAI SSE deltas into the assistant dict the loop consumes.

    Tool calls stream as fragments keyed by `index`: the first fragment
    carries id and name, later ones append to `arguments`. They are
    accumulated by index and only handed over once the stream ends —
    a half-received argument string is not a call. On a stop, calls
    still being received are dropped for the same reason.
    """
    content: list[str] = []
    thinking: list[str] = []
    finish_reason = ""
    calls_by_index: dict[int, dict] = {}
    stopped = False
    for line in lines:
        if stop_requested is not None and stop_requested():
            stopped = True
            break
        if not line.startswith(SSE_DATA_PREFIX):
            continue
        data = line[len(SSE_DATA_PREFIX) :].strip()
        if data == SSE_DONE_MARKER:
            break
        frame = json.loads(data)
        choice = (frame.get("choices") or [{}])[0]
        if choice.get("finish_reason"):
            finish_reason = choice["finish_reason"]
        delta = choice.get("delta") or {}
        text = delta.get("content")
        if text:
            content.append(text)
            on_delta("content", text)
        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
        if reasoning:
            thinking.append(reasoning)
            on_delta("thinking", reasoning)
        for fragment in delta.get("tool_calls") or []:
            index = fragment.get("index", 0)
            call = calls_by_index.setdefault(
                index, {"id": "", "function": {"name": "", "arguments": ""}}
            )
            if fragment.get("id"):
                call["id"] = fragment["id"]
            function = fragment.get("function") or {}
            if function.get("name"):
                call["function"]["name"] += function["name"]
            if function.get("arguments"):
                call["function"]["arguments"] += function["arguments"]
    message: dict = {
        "finish_reason": finish_reason,
        "role": "assistant",
        "content": "".join(content),
        "tool_calls": [] if stopped else [calls_by_index[i] for i in sorted(calls_by_index)],
    }
    if thinking:
        message["thinking"] = "".join(thinking)
    return message


def _assemble_ollama_stream(lines, on_delta, stop_requested) -> dict:
    """Fold Ollama NDJSON frames into the assistant dict.

    Ollama streams content and thinking as fragments and delivers each
    tool call whole inside one frame, so calls are appended as they
    arrive and dropped on a stop only if the stream was cut before
    `done`.
    """
    content: list[str] = []
    thinking: list[str] = []
    tool_calls: list[dict] = []
    stopped = False
    done_reason = ""
    for line in lines:
        if stop_requested is not None and stop_requested():
            stopped = True
            break
        frame = json.loads(line)
        message = frame.get("message") or {}
        text = message.get("content")
        if text:
            content.append(text)
            on_delta("content", text)
        reasoning = message.get("thinking")
        if reasoning:
            thinking.append(reasoning)
            on_delta("thinking", reasoning)
        tool_calls.extend(message.get("tool_calls") or [])
        if frame.get("done"):
            done_reason = frame.get("done_reason") or ""
            break
    assembled: dict = {
        "done_reason": done_reason,
        "role": "assistant",
        "content": "".join(content),
        "tool_calls": [] if stopped else tool_calls,
    }
    if thinking:
        assembled["thinking"] = "".join(thinking)
    return assembled


class OllamaClient:
    """Minimal chat client with tool-calling and image attachment.

    One client, two wire protocols, chosen per endpoint:
    Ollama /api/chat (local daemon and cloud) or OpenAI
    /v1/chat/completions (the llama-swaps and OpenRouter).
    """

    def __init__(self, config: ModelConfig | None = None) -> None:
        self.config = config or ModelConfig.from_environment()
        # What this client has spent, accumulated across every call it
        # makes. Added 2026-09-06 because the harness had NO token
        # accounting: a turn assembling 12.5k of prompt was billing
        # 25.8k, and nothing in the loop could see it. The eye's
        # spending is folded in here too (see VisionDescriber.describe),
        # so one run's record covers the writer AND its examiner.
        self.spent = TurnCost()

    def _build_request(self, path: str, payload: dict | None) -> urllib.request.Request:
        request = urllib.request.Request(
            self.config.endpoint.rstrip("/") + path,
            data=json.dumps(payload).encode("utf-8") if payload else None,
            headers={"Content-Type": "application/json"},
            method="POST" if payload else "GET",
        )
        if self.config.api_key:
            request.add_header("Authorization", f"Bearer {self.config.api_key}")
        if self.config.is_openrouter:
            for header, value in OPENROUTER_APP_HEADERS.items():
                request.add_header(header, value)
        return request

    def _request(self, path: str, payload: dict | None, timeout_seconds: int):
        request = self._build_request(path, payload)
        with urllib.request.urlopen(
            request, timeout=timeout_seconds, context=_tls_context()
        ) as response:
            return json.loads(response.read().decode("utf-8"))

    def _stream_lines(self, path: str, payload: dict, timeout_seconds: int):
        """Yield the response body line by line as it arrives.

        Both wire protocols stream newline-delimited frames: Ollama
        emits one JSON object per line, OpenAI-protocol servers emit
        SSE `data: {...}` lines. The generator holds the socket open,
        so a consumer that stops iterating (a cancel) closes it.
        """
        request = self._build_request(path, payload)
        with urllib.request.urlopen(
            request, timeout=timeout_seconds, context=_tls_context()
        ) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", "replace").strip()
                if line:
                    yield line

    def _chat_path(self) -> str:
        return OPENAI_CHAT_PATH if self.config.uses_openai_protocol else CHAT_PATH

    def _chat_payload(self, messages, tools=None) -> dict:
        if self.config.uses_openai_protocol:
            payload = {
                "model": self.config.model,
                "messages": _to_openai_messages(messages),
                "temperature": self.config.temperature,
                # Ceiling only; the wall clock is config.request_timeout_seconds.
                "max_tokens": self.config.max_completion_tokens,
                "stream": False,
            }
            if tools:
                payload["tools"] = _to_openai_tools(tools)
            return payload
        payload = {
            "model": self.config.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.config.temperature,
                "num_ctx": self.config.context_length,
            },
        }
        if tools:
            payload["tools"] = tools
        return payload

    def _claude_code_transport(self, timeout_seconds: int = 0) -> ClaudeCodeTransport:
        """This config's headless-CLI transport.

        Built per call, holding no conversation: the CLI lane is as
        stateless as the HTTP lanes, so `AgentSession.messages` stays
        the single source of truth for the conversation. `timeout_seconds`
        overrides the lane ceiling for the preflight, which asks for one
        token and must not wait out a whole modeling turn.
        """
        return ClaudeCodeTransport(
            model=self.config.model,
            effort=self.config.claude_code_effort,
            binary_path=self.config.claude_code_binary_path,
            timeout_seconds=timeout_seconds or self.config.request_timeout_seconds,
        )

    def check_connection(self) -> ConnectionStatus:
        """Verify the model is reachable BEFORE the first real turn.

        Tries the configured endpoint, then falls back to direct cloud if
        a key is available — and reports which path actually worked, so a
        misconfiguration is a one-line diagnosis instead of a mystery
        timeout mid-conversation.
        """
        if self.config.uses_claude_code:
            transport = self._claude_code_transport(PREFLIGHT_TIMEOUT_SECONDS)
            from blended.agent.tool_disclosure import core_ops, offered_tools
            from blended.agent.tools import SERVICE_TOOL_NAMES, TOOL_SCHEMAS

            # The preflight ping carries the REAL envelope schema — the
            # disclosed set (OT-25) — so a CLI too old for --json-schema
            # fails here rather than mid-conversation.
            ok, detail = transport.check_connection(
                offered_tools(TOOL_SCHEMAS, core_ops(), SERVICE_TOOL_NAMES)
            )
            return ConnectionStatus(ok, CLAUDE_CODE_ENDPOINT, detail)
        attempts = [self.config.endpoint]
        if (
            not self.config.is_cloud_endpoint
            and not self.config.uses_openai_protocol
            and self.config.api_key
        ):
            # Ollama lanes fall back to direct cloud; a llama-swap lane
            # has ONE server and ONE credential — no fallback.
            attempts.append(CLOUD_ENDPOINT)

        failures: list[str] = []
        codes: set[int] = set()
        for endpoint in attempts:
            probe_client = OllamaClient(self.config.with_endpoint(endpoint))
            try:
                probe_client._request(
                    probe_client._chat_path(),
                    probe_client._chat_payload(
                        [{"role": "user", "content": "ping"}]
                    ),
                    PREFLIGHT_TIMEOUT_SECONDS,
                )
            except urllib.error.HTTPError as http_error:
                body = http_error.read().decode("utf-8", "replace")[:200]
                codes.add(http_error.code)
                failures.append(f"{endpoint}: HTTP {http_error.code} {body}")
                continue
            except Exception as error:  # noqa: BLE001 — diagnostic path
                failures.append(f"{endpoint}: {error}")
                continue
            self.config = self.config.with_endpoint(endpoint)
            if BMB_ENDPOINT in endpoint:
                route = f"llama-swap on bmb ({BMB_ENDPOINT})"
            elif BIG_ENDPOINT in endpoint:
                route = f"llama-swap on big ({BIG_ENDPOINT})"
            elif CLOUD_ENDPOINT in endpoint:
                route = "direct cloud (Bearer key)"
            else:
                route = "local daemon (proxying cloud models if signed in)"
            return ConnectionStatus(True, endpoint, f"{self.config.model} via {route}")

        # The hint follows the OBSERVED failure, never the mere absence
        # of a key. A signed-in daemon needs no key, so keying the hint
        # off `api_key == ""` printed "no OLLAMA_API_KEY" over a 404 and
        # sent a real debugging session chasing auth that was fine.
        hint = ""
        if 404 in codes:
            served_list_path = (
                "/v1/models" if self.config.uses_openai_protocol else TAGS_PATH
            )
            hint = (
                f" Nothing at {self.config.endpoint} serves "
                f"{self.config.model!r}. A model id picks its own server: "
                f"bmb's llama-swap serves {', '.join(BMB_MODEL_IDS)}; "
                f"big's llama-swap at {BIG_ENDPOINT} serves "
                f"{', '.join(BIG_MODEL_IDS)}; a `claude-code:` id rides "
                f"the local headless CLI; a `vendor/model` id rides "
                f"OpenRouter; every other id rides the "
                f"local daemon, which serves cloud models once "
                f"`ollama signin` ran plus whatever is pulled locally. "
                f"Check the served list with "
                f"`curl {self.config.endpoint}{served_list_path}`."
            )
        elif codes & {401, 403} and not self.config.api_key:
            if BMB_ENDPOINT in self.config.endpoint:
                hint = (
                    " bmb's llama-swap requires its API key (it 401s "
                    "without one, verified live 2026-08-23). The key lives "
                    "on bmb at ~/llm/.api-key — paste it into the addon's "
                    "API key preference. Finder-launched Blender does not "
                    "inherit your shell environment."
                )
            elif BIG_ENDPOINT in self.config.endpoint:
                hint = (
                    f" big's llama-swap takes no API key (it answers 200 "
                    f"with and without a bearer, verified 2026-09-03), so "
                    f"a 401 here means something else is listening on "
                    f"{BIG_ENDPOINT} — check `ssh big \"bash -lc "
                    f"'journalctl --user -u llama-swap -n 20'\"`."
                )
            elif self.config.is_openrouter:
                hint = (
                    f" OpenRouter needs its key: put it in "
                    f"{OPENROUTER_API_KEY_FILE} (bare `sk-or-...` or an "
                    f"`OPENROUTER_API_KEY=` line)."
                )
            else:
                hint = (
                    f" No {API_KEY_ENVIRONMENT_VARIABLE} visible to this "
                    f"process — on macOS, Blender launched from Finder does "
                    f"not inherit your shell environment. Either run "
                    f"`ollama signin` so the local daemon handles auth, "
                    f"launch Blender from a terminal, or paste the key into "
                    f"the addon preferences."
                )
        return ConnectionStatus(False, self.config.endpoint, "; ".join(failures) + hint)

    def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        on_delta: Callable[[str, str], None] | None = None,
        stop_requested: Callable[[], bool] | None = None,
    ) -> dict:
        """One chat completion. Returns the assistant message dict.

        With `on_delta(kind, text)` the reply is STREAMED: each content
        or thinking fragment is delivered as it arrives (kind in
        {"content", "thinking"}) and the same assistant dict is
        assembled from the fragments. `stop_requested()` is polled per
        frame; when it turns true the socket is closed and whatever
        arrived so far is returned — which is how a user's Stop lands
        mid-generation instead of after it.
        """
        if self.config.uses_claude_code:
            # A subprocess, not a socket: the transport owns the frame
            # protocol, the schema-constrained tool calls, and the same
            # on_delta / stop_requested contract.
            transport = self._claude_code_transport()
            message = transport.chat(messages, tools, on_delta, stop_requested)
            if transport.last_turn_cost is not None:
                self.spent = self.spent.plus(transport.last_turn_cost)
            return message
        payload = self._chat_payload(messages, tools)
        streaming = on_delta is not None
        if streaming:
            payload["stream"] = True
        try:
            if streaming:
                return self._chat_streamed(payload, on_delta, stop_requested)
            body = self._request(
                self._chat_path(), payload, self.config.request_timeout_seconds
            )
        except urllib.error.HTTPError as http_error:
            detail = http_error.read().decode("utf-8", "replace")[:300]
            raise RuntimeError(
                f"Model call failed: HTTP {http_error.code} from "
                f"{self.config.endpoint}. {detail}"
            ) from http_error
        except urllib.error.URLError as url_error:
            raise RuntimeError(
                f"Could not reach the model at {self.config.endpoint}: "
                f"{url_error}. Is the server running, and is "
                f"{self.config.model!r} available?"
            ) from url_error
        self.spent = self.spent.plus(_turn_cost_from_body(body))
        # OT-22: a cut reply is an error, never a result.
        check_reply_fits(body, self.config.context_tokens, self.config.endpoint)
        if self.config.uses_openai_protocol:
            return _assistant_message_from_openai(body)
        return body.get("message", {})

    def _chat_streamed(self, payload: dict, on_delta, stop_requested) -> dict:
        lines = self._stream_lines(
            self._chat_path(), payload, self.config.request_timeout_seconds
        )
        if self.config.uses_openai_protocol:
            message = _assemble_openai_stream(lines, on_delta, stop_requested)
        else:
            message = _assemble_ollama_stream(lines, on_delta, stop_requested)
        # The assemblers carry the stream's own end signal (OT-22).
        check_reply_fits(message, self.config.context_tokens, self.config.endpoint)
        return message


def _turn_cost_from_body(body: dict) -> TurnCost:
    """One HTTP reply's usage, on either wire protocol.

    Ollama reports `prompt_eval_count` / `eval_count`; the OpenAI
    protocol reports a `usage` object, and llama-swap fills it in.
    Neither exposes a cache split or a price, so those stay zero — the
    point is that a run's record says how many tokens it moved on EVERY
    lane, not only the one that prices itself.
    """
    usage = body.get("usage") or {}
    if usage:
        return TurnCost(
            api_calls=1,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )
    return TurnCost(
        api_calls=1,
        input_tokens=int(body.get("prompt_eval_count") or 0),
        output_tokens=int(body.get("eval_count") or 0),
    )



class EyeUnreachable(RuntimeError):
    """The eye could not be reached on a path where that is fatal.

    A distinct type rather than a traceback a caller has to string-match:
    `scripts/photo_to_model.py` records `eye_reachable` in its summary,
    and deciding that by grepping a truncated traceback would be a guess
    dressed as a measurement.
    """


class VisionDescriber:
    """Turns rendered images into text for a writer that cannot see.

    Kept as a separate one-shot call rather than a second conversation:
    the eye gets the images plus a focused question and returns a
    description. It holds no history, makes no tool calls, and never
    decides anything — so a High Usage model is spent only on the turns
    that actually contain a render, instead of on every turn.
    """

    def __init__(self, client: OllamaClient, vision_model: str) -> None:
        self.client = client
        self.vision_model = vision_model

    def describe(
        self, image_paths: list[Path], question: str = "", prompt: str = ""
    ) -> str:
        """Describe the images, or answer a caller's OWN prompt verbatim.

        `prompt` replaces the template entirely: the examiner supplies a
        fully-rendered prompt with a closed tag vocabulary and a JSON
        output contract, and prepending advisory prose written for the
        writer would contaminate it. Empty `prompt` keeps the writer's
        own question wording; both paths get the image placeholders,
        because both hand the eye several same-size renders at once.
        """
        if prompt:
            text = prompt
        else:
            text = VISION_DESCRIBE_PROMPT
            if question:
                text += f"\n\nThe agent specifically wants to know: {question}"
        message = {
            "role": "user",
            "content": _image_placeholders(len(image_paths)) + text,
            "images": _encode_images(image_paths),
        }
        # ONE routing rule for the eye, shared with the preflight:
        # `self.vision_model` is the describer's own eye (the examiner
        # passes its own), so it is pushed onto the config first.
        eye_client = OllamaClient(
            replace(self.client.config, vision_model=self.vision_model)
            .eye_config()
        )
        reply = eye_client.chat([message])
        # The eye rides its own client (its own server, its own key), so
        # its spending would otherwise vanish from the run's record.
        # Measured 2026-09-06: examination costs MORE than the build it
        # judges — 10 calls per brief against the writer's 14 for five
        # turns — so hiding it would hide the largest line item.
        self.client.spent = self.client.spent.plus(eye_client.spent)
        return (reply.get("content") or "").strip()


def _image_placeholders(image_count: int) -> str:
    """One labelled `[img]` placeholder per image, separated by text.

    Without placeholders, Ollama's renderer prepends `[img-0][img-1]...`
    back to back, and llama.cpp's mtmd tokenizer merges *consecutive*
    same-size bitmaps into video frames for the qwen-vl family
    (ollama/ollama#17321, ggml-org/llama.cpp#24303, both open). Every
    render this harness makes is the same size, so a two-image message
    arrived as ONE fused image and the examiner correctly answered
    `cannot_tell` — it had never been shown the render under review.
    Measured 2026-08-22 against qwen3-vl:8b on ollama 0.32.14: 1055
    prompt tokens fused, 2089 with these placeholders, and the eye then
    names both objects and tracks their order when swapped.

    The renderer substitutes placeholders in order, so `Image 1` is the
    first path — which is what `examiner.md.j2` means by "the FIRST
    image". The Claude Code lane needs no such workaround (it delivers
    images unfused already) but splices its real image blocks in at
    these same positions, which is why the token is one constant.
    """
    return (
        "".join(
            f"Image {index}:\n{IMAGE_PLACEHOLDER_TOKEN}\n"
            for index in range(1, image_count + 1)
        )
        + "\n"
    )


def _encode_images(image_paths: list[Path]) -> list[str]:
    """Base64-encode images for the chat API."""
    encoded: list[str] = []
    for image_path in image_paths:
        image_bytes = Path(image_path).read_bytes()
        encoded.append(base64.b64encode(image_bytes).decode("ascii"))
    return encoded


def deliver_images(
    message: dict,
    image_paths: list[Path],
    client: OllamaClient,
    header: str,
    question: str = "",
    prompt: str = "",
    *,
    eye_failure_is_fatal: bool = False,
) -> str:
    """Put images in front of the writer on either eye configuration.

    ONE place decides how pixels reach a model, because there are two
    kinds of caller now — a tool result carrying renders and a user
    message carrying a reference photo — and they must not drift apart.

    Native (`message["images"]`, placeholders spliced into the content)
    when the writer is its own eye; otherwise the eye describes the
    images and its description is appended under `header`. Returns the
    eye's text, or "" on the native path. `message["content"]` is
    mutated in place.

    `eye_failure_is_fatal` decides what an unreachable eye MEANS, and
    the two callers genuinely differ. A blind turn about the writer's
    own render is recoverable — the gate report still describes the
    mesh, so a note is honest. A blind turn about the USER'S PHOTOGRAPH
    has no specification at all: the reference-photo prompt deliberately
    names no shape, so a writer handed `EYE_UNREACHABLE_NOTE` instead of
    pixels will invent an object and the run will look like a success.
    """
    if not client.config.uses_separate_eye:
        # Placeholders on this branch too: `claude_code.render_call`
        # splices real image blocks at each `[img]` and only appends
        # leftovers at the end, so placing them decides where the
        # writer sees the picture relative to the text.
        message["content"] = _image_placeholders(len(image_paths)) + message["content"]
        message["images"] = _encode_images(image_paths)
        return ""
    describer = VisionDescriber(client, client.config.vision_model)
    try:
        description = describer.describe(image_paths, question, prompt)
    except Exception as eye_error:
        if eye_failure_is_fatal:
            raise EyeUnreachable(
                f"{client.config.vision_model} could not read the "
                f"reference image(s): {eye_error}"
            ) from eye_error
        description = EYE_UNREACHABLE_NOTE.format(error=eye_error)
    message["content"] = (
        f"{message['content']}\n\n"
        f"--- {header} ({client.config.vision_model}) ---\n"
        f"{description}"
    )
    return description


# Where a tool call is executed. The loop runs on a worker thread (the
# model call blocks for seconds to minutes) but `bpy` is main-thread
# only, so the live-Blender frontend has to move execution somewhere
# else. That seam is a CONSTRUCTOR ARGUMENT, never a patched module
# attribute: `send` resolves its tools by local import, so a patch on
# this module is invisible to it. When the seam was a patch, every tool
# call ran bpy on the worker thread and Blender segfaulted inside its
# own draw loop with nothing in any traceback.
ToolDispatch = Callable[[str, dict, Path], tuple[str, list[Path]]]


# OT-16: the working agreement's "stop after three honest attempts", as
# code. Counted per object, per turn, over consecutive gate verdicts
# that did not reach `done`; a verdict that passes resets that object's
# count. With op tools a retry is one cheap, precise call, so the cap
# no longer costs capability — it stops a turn that is rediscovering
# one failure (measured 2026-08-22: iteration 5 spent its whole budget
# on the same boolean failure).
MAXIMUM_GATE_FAILURES_PER_OBJECT = 3
GATE_CAP_TOOL_RESULT = "Not run: the turn stopped at the gate-failure cap."
GATE_CAP_ANSWER = (
    "Stopped: {object_name!r} failed the gate {count} times in a row "
    "(cap {cap}). Last verdict: {verdict}. The contact sheet is attached. "
    "Tell me how to proceed."
)


# OT-17: a token budget per turn, checked at the seam after every model
# reply. Derived from measurement, not chosen: the tool-call budget is
# 24 calls, so the budget is 24 x the heaviest per-call bill measured
# on the heaviest lane, plus a fifth for a long answer.
#   2026-09-06, Claude Code lane, 8 tools: 25,851 tokens per call
#     -> 24 x 25,851 = 620k, budget 750k.
#   2026-09-10, same lane, 50 tools (OT-3): iteration 68 billed 931,851
#     tokens in 16 calls = 58,241 per call (91% cache reads; the 50-tool
#     schema travels with every API call), and the 750k budget stopped a
#     legitimate turn at call 16 -> 24 x 58,241 = 1.40M, budget 1.7M.
# The wrong number is kept above on purpose: it is the measured price of
# one tool per op on this lane, and OT-13's decision reads it.
MAXIMUM_TURN_TOKENS = 1_700_000
TOKEN_CAP_TOOL_RESULT = "Not run: the turn stopped at the token budget."
TOKEN_CAP_ANSWER = (
    "Stopped after {tokens:,} tokens in one turn (budget {budget:,}) without "
    "reaching an answer. Tell me how to narrow this."
)


# OT-11: a session may withhold tools. The schema is not offered to the
# model, and a call to it anyway is refused here — a lane without
# constrained decoding can still name a tool it was never shown.
DISABLED_TOOL_REFUSAL = (
    "{tool_name} is disabled in this session. Build with the op tools; if "
    "the vocabulary cannot express what you need, say so in your answer."
)


def _tokens_since(start: TurnCost, now: TurnCost) -> int:
    """Tokens billed between two readings of a client's `spent`: input
    (including cache reads and writes) plus output."""
    return (now.billed_input_tokens - start.billed_input_tokens) + (
        now.output_tokens - start.output_tokens
    )


def _plan_step_or_none(arguments: dict) -> int | None:
    """The call's plan_step for the record; a malformed one is None here
    and reported by `plan_step_of` where the loop reads it."""
    try:
        return plan_step_of(arguments)
    except ValueError:
        return None


def dispatch_here(
    tool_name: str, arguments: dict, output_directory: Path
) -> ToolOutcome:
    """Execute the tool on the CALLING thread. Main thread only."""
    from blended.agent.tools import dispatch_tool

    return dispatch_tool(tool_name, arguments, output_directory)


@dataclass
class AgentSession:
    """A multi-turn modeling conversation against a live Blender scene."""

    client: OllamaClient = field(default_factory=OllamaClient)
    output_directory: Path = Path("_renders/agent")
    # Measured, not guessed. three_leg_stool needs 17 calls to build and
    # verify itself (iteration 10) and then has nothing left to answer
    # with — three consecutive runs ended in the exhaustion string
    # holding a finished asset. 24 leaves room to report and to absorb
    # one failed chunk, while still capping a runaway loop.
    maximum_tool_calls_per_turn: int = 24
    maximum_gate_failures_per_object: int = MAXIMUM_GATE_FAILURES_PER_OBJECT
    maximum_turn_tokens: int = MAXIMUM_TURN_TOKENS
    # Tool names withheld from the model this session (OT-11).
    disabled_tools: frozenset[str] = frozenset()
    messages: list[dict] = field(default_factory=list)
    # A plain function as a dataclass default: __init__ assigns it to the
    # INSTANCE, so `self.dispatch(...)` calls it unbound — no phantom
    # `self` argument. Frontends override it; nothing patches it.
    dispatch: ToolDispatch = dispatch_here
    # Set from ANY thread (the UI) to stop the turn at the next seam:
    # before the next model call, per streamed frame, and before each
    # tool call. Efficient dismissal and correction are guidelines G8/G9
    # of Amershi et al., Guidelines for Human-AI Interaction
    # (DOI 10.1145/3290605.3300233); streaming (below) is G11, make
    # clear why the system did what it did — while it is doing it.
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    # Stream model replies as `content_delta` / `thinking_delta` events.
    # Off by default so scripted clients and batch drivers keep the
    # one-shot `chat(messages, tools)` contract; the live UI turns it on.
    stream_replies: bool = False
    # Require a declared plan before any scene-changing tool this turn.
    # Off by default so scripted clients and the 3DCodeBench batch
    # driver keep their current contract; the live UI and the chat E2E
    # gate turn it on. A plan belongs to one turn and is reset in send().
    require_plan: bool = False

    def cancel(self) -> None:
        self.cancel_requested.set()

    def __post_init__(self) -> None:
        if not self.messages:
            from blended.agent.system_prompt import build_system_prompt

            self.messages.append({"role": "system", "content": build_system_prompt()})

    def send(
        self,
        user_text: str,
        on_event=None,
        reference_images: tuple[Path, ...] = (),
    ) -> str:
        """Run one user turn to completion, executing tool calls.

        `reference_images` are the USER's pictures of the object to
        build — normalized PNGs from
        `blended.capture.reference_photo.normalize_reference_photo` —
        not renders of the scene. They ride the user message, so they
        stay in the history for every later refinement turn and are
        never re-sent.

        `on_event(kind, text)` is called for streaming UI updates with
        kind in {"thinking", "tool", "result", "answer", "vision",
        "plan", "step", "render", "reference"} plus, when
        `stream_replies` is on, {"content_delta", "thinking_delta"}
        fragments that precede the whole "thinking"/"answer" event.
        Returns the assistant's final text.
        """

        offered_tools = self.offered_tools()
        offered_fingerprint_text = offered_fingerprint(offered_tools)

        def emit(kind: str, text: str) -> None:
            if on_event is not None:
                on_event(kind, text)

        user_message: dict = {"role": "user", "content": user_text}
        if reference_images:
            user_message["content"] = f"{REFERENCE_PHOTO_LEAD_IN}\n\n{user_text}"
            # Picture first, then what the eye said about it — the same
            # ordering the render path uses, so the panel can pair them.
            for reference_path in reference_images:
                emit("reference", str(reference_path))
            # FATAL here, unlike the render path: the reference-photo
            # prompt names no shape, so a writer handed a note instead
            # of pixels has no specification and invents an object.
            description = deliver_images(
                user_message,
                list(reference_images),
                self.client,
                REFERENCE_IMAGE_HEADER,
                prompt=REFERENCE_PHOTO_READ_PROMPT,
                eye_failure_is_fatal=True,
            )
            if description:
                emit("vision", description)
        self.messages.append(user_message)

        self.cancel_requested.clear()
        executed_tool_call_count = 0
        # Per-turn plan state. A plan belongs to one turn: declared at
        # the start, advanced through its steps, discarded at the end.
        turn_plan: TurnPlan | None = None
        # Per-turn account of unlinked intermediates (OT-5).
        ledger = IntermediateLedger()
        # Per-turn count of consecutive gate failures per object (OT-16).
        gate_failures: dict[str, int] = {}
        # Where this turn's spending starts (OT-17). `spent` accumulates
        # for the session; the budget is per turn.
        spent_at_turn_start = self.client.spent
        preflight_reported = False
        while executed_tool_call_count < self.maximum_tool_calls_per_turn:
            # OT-22: refuse to send what will not fit, with the sizes named,
            # rather than let the transport truncate. A lane with no
            # measured context is reported once and not checked.
            try:
                report = preflight(
                    self.messages,
                    offered_tools,
                    self.client.config.context_tokens,
                    self.client.config.max_completion_tokens,
                    self.client.config.endpoint,
                )
            except ContextExceeded as too_big:
                emit("answer", str(too_big))
                return str(too_big)
            if not report.checked and not preflight_reported:
                preflight_reported = True
                emit("preflight", f"context not checked: {report.reason}")
            if self.stream_replies:
                assistant_message = self.client.chat(
                    self.messages,
                    offered_tools,
                    on_delta=lambda kind, text: emit(f"{kind}_delta", text),
                    stop_requested=self.cancel_requested.is_set,
                )
            else:
                assistant_message = self.client.chat(self.messages, offered_tools)
            self.messages.append(assistant_message)
            if self.cancel_requested.is_set():
                return self._cancel_turn(assistant_message, emit)

            thinking_text = assistant_message.get("thinking")
            if thinking_text:
                emit("thinking", thinking_text)

            tool_calls = assistant_message.get("tool_calls") or []
            # OT-17: the seam. A reply that is already an answer ends the
            # turn whatever it cost; a reply that wants more tool calls
            # is refused when the turn's tokens exceed the budget.
            turn_tokens = _tokens_since(spent_at_turn_start, self.client.spent)
            if tool_calls and turn_tokens > self.maximum_turn_tokens:
                self._answer_pending_tool_calls(assistant_message, TOKEN_CAP_TOOL_RESULT)
                exhausted = TOKEN_CAP_ANSWER.format(
                    tokens=turn_tokens, budget=self.maximum_turn_tokens
                )
                emit("answer", exhausted)
                return exhausted
            if not tool_calls:
                # OT-5: a turn may not end while an unlinked intermediate
                # is unresolved. The refusal reaches the model as the next
                # user message and counts against the budget so a model
                # that never resolves still terminates.
                refusal = ledger.refusal()
                if refusal:
                    executed_tool_call_count += 1
                    emit("result", refusal)
                    self.messages.append({"role": "user", "content": refusal})
                    continue
                answer = assistant_message.get("content", "")
                emit("answer", answer)
                return answer

            for tool_call in tool_calls:
                function_block = tool_call.get("function", {})
                tool_name = function_block.get("name", "")
                raw_arguments = function_block.get("arguments", {})
                arguments = (
                    json.loads(raw_arguments)
                    if isinstance(raw_arguments, str)
                    else raw_arguments
                )
                if self.cancel_requested.is_set():
                    return self._cancel_turn(assistant_message, emit)
                if tool_name in self.disabled_tools:
                    refusal = DISABLED_TOOL_REFUSAL.format(tool_name=tool_name)
                    emit("tool", f"{tool_name}({json.dumps(arguments)})")
                    executed_tool_call_count += 1
                    emit("result", refusal)
                    emit(
                        TOOL_EVENT_KIND,
                        encode_tool_event(
                            ToolEvent(
                                tool_name=tool_name,
                                arguments=arguments,
                                ok=False,
                                stage_reached="",
                                wall_time_s=0.0,
                                plan_step=_plan_step_or_none(arguments),
                                refusal=refusal,
                                offered_tools_fingerprint=offered_fingerprint_text,
                            )
                        ),
                    )
                    self.messages.append({
                        "role": "tool",
                        "content": refusal,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.get("id", ""),
                    })
                    continue
                # Plan enforcement: a scene-changing tool with no plan
                # declared this turn is refused, not dispatched. The
                # refusal counts against the tool-call budget so a loop
                # that never plans still terminates. The model sees the
                # refusal as a tool result and can correct itself by
                # declaring a plan on its next turn.
                if (
                    self.require_plan
                    and plan_required_for(tool_name)
                    and turn_plan is None
                ):
                    emit("tool", f"{tool_name}({json.dumps(arguments)})")
                    executed_tool_call_count += 1
                    emit("result", MISSING_PLAN_REFUSAL)
                    emit(
                        TOOL_EVENT_KIND,
                        encode_tool_event(
                            ToolEvent(
                                tool_name=tool_name,
                                arguments=arguments,
                                ok=False,
                                stage_reached="",
                                wall_time_s=0.0,
                                plan_step=_plan_step_or_none(arguments),
                                refusal=MISSING_PLAN_REFUSAL,
                                offered_tools_fingerprint=offered_fingerprint_text,
                            )
                        ),
                    )
                    self.messages.append({
                        "role": "tool",
                        "content": MISSING_PLAN_REFUSAL,
                        "tool_name": tool_name,
                        "tool_call_id": tool_call.get("id", ""),
                    })
                    continue
                emit("tool", f"{tool_name}({json.dumps(arguments)})")
                executed_tool_call_count += 1
                dispatched_at = time.perf_counter()
                try:
                    outcome = self.dispatch(tool_name, arguments, self.output_directory)
                except Exception as tool_error:  # noqa: BLE001 — reported to the model
                    import traceback

                    outcome = ToolOutcome(
                        f"Tool raised {type(tool_error).__name__}: {tool_error}\n"
                        f"{traceback.format_exc()[:1500]}",
                        ok=False,
                    )
                wall_time_s = time.perf_counter() - dispatched_at
                result_text = outcome.text
                image_paths = list(outcome.images)
                ledger.record(tool_name, outcome)
                emit("result", result_text)
                # The structured record of this call (OT-8): what the
                # miner and the exporter read, beside the text the model
                # reads.
                emit(
                    TOOL_EVENT_KIND,
                    encode_tool_event(
                        ToolEvent(
                            tool_name=tool_name,
                            arguments=(
                                outcome.validated_arguments
                                if outcome.validated_arguments is not None
                                else arguments
                            ),
                            ok=outcome.ok,
                            stage_reached=outcome.stage_reached,
                            wall_time_s=wall_time_s,
                            plan_step=_plan_step_or_none(arguments),
                            gates=outcome.gates,
                            images=tuple(str(path) for path in image_paths),
                            hatch_reason=outcome.hatch_reason,
                            source_sha256=outcome.source_sha256,
                            offered_tools_fingerprint=offered_fingerprint_text,
                        )
                    ),
                )

                # When the model declared its plan, parse and store it
                # for this turn, then emit a plan event so the panel can
                # show the steps and progress bar. The plan was already
                # validated inside dispatch_tool; re-parse from the
                # arguments to get the TurnPlan object.
                if tool_name == PLAN_TOOL_NAME:
                    try:
                        turn_plan = parse_plan_arguments(arguments)
                        emit("plan", encode_plan_event(turn_plan))
                    except ValueError:
                        # dispatch_tool already returned a FAILED result
                        # naming the problem; no plan event to emit.
                        turn_plan = None

                # When the call carried a plan_step, emit a step event
                # and advance the plan's current_step so a later plan
                # event is consistent. An out-of-range step clamps
                # rather than breaking the panel.
                step_index = plan_step_of(arguments)
                if step_index is not None and turn_plan is not None:
                    turn_plan = turn_plan.with_step(step_index)
                    emit("step", str(step_index))

                tool_message: dict = {
                    "role": "tool",
                    "content": result_text,
                    "tool_name": tool_name,
                    # Carried so an OpenAI-protocol backend (llama-swap)
                    # can match the result to the assistant's call;
                    # Ollama ignores unknown keys.
                    "tool_call_id": tool_call.get("id", ""),
                }
                if image_paths:
                    # Emit render events BEFORE the vision event so the
                    # panel can pair the picture with what the eye said.
                    # Emitted in both eye configs because the panel shows
                    # the render either way.
                    for image_path in image_paths:
                        emit("render", str(image_path))
                    description = deliver_images(
                        tool_message,
                        image_paths,
                        self.client,
                        RENDER_IMAGE_HEADER,
                        question=arguments.get("look_for", ""),
                    )
                    if description:
                        emit("vision", description)
                self.messages.append(tool_message)

                # OT-16: count consecutive gate failures per object; a
                # pass resets. At the cap the turn stops here, with a
                # contact sheet, instead of burning the rest of the
                # tool-call budget on the same failure.
                for gate in outcome.gates:
                    gated_name = str(gate.get("object_name", ""))
                    if gate.get("stage_reached") == STAGE_DONE:
                        gate_failures.pop(gated_name, None)
                    else:
                        gate_failures[gated_name] = gate_failures.get(gated_name, 0) + 1
                capped = [
                    name
                    for name, count in gate_failures.items()
                    if count >= self.maximum_gate_failures_per_object
                ]
                if capped:
                    return self._stop_at_gate_cap(
                        assistant_message, capped[0], gate_failures[capped[0]], outcome, emit
                    )

        exhausted = (
            f"Stopped after {executed_tool_call_count} tool calls in one turn "
            f"(budget {self.maximum_tool_calls_per_turn}) without reaching an "
            f"answer. Tell me how to narrow this."
        )
        emit("answer", exhausted)
        return exhausted

    def offered_tools(self) -> list[dict]:
        """The schemas a call carries (OT-25): the service tools, every
        reader and the derived core set, minus any withheld tool. Every
        other facade op is reachable by name after `search_ops`."""
        from blended.agent.tool_disclosure import core_ops, offered_tools
        from blended.agent.tools import SERVICE_TOOL_NAMES, TOOL_SCHEMAS

        return [
            tool
            for tool in offered_tools(TOOL_SCHEMAS, core_ops(), SERVICE_TOOL_NAMES)
            if tool["function"]["name"] not in self.disabled_tools
        ]

    def offered_tools_fingerprint(self) -> str:
        return offered_fingerprint(self.offered_tools())

    def _answer_pending_tool_calls(self, assistant_message: dict, text: str) -> None:
        """Give every tool_call the model issued a tool result — an
        OpenAI-protocol backend rejects the next turn otherwise."""
        # Positional, not by id: the tool results appended since this
        # assistant message answer its calls in order, and a lane that
        # mints no ids (a scripted client, Ollama) must not get a second
        # result for a call that already has one.
        # The message being closed is the LATEST occurrence: a scripted
        # client may replay one dict object twice.
        position = next(
            (
                index
                for index in range(len(self.messages) - 1, -1, -1)
                if self.messages[index] is assistant_message
            ),
            len(self.messages),
        )
        already_answered = sum(
            1 for message in self.messages[position + 1 :] if message.get("role") == "tool"
        )
        for tool_call in (assistant_message.get("tool_calls") or [])[already_answered:]:
            self.messages.append(
                {
                    "role": "tool",
                    "content": text,
                    "tool_name": tool_call.get("function", {}).get("name", ""),
                    "tool_call_id": tool_call.get("id", ""),
                }
            )

    def _cancel_turn(self, assistant_message: dict, emit) -> str:
        """Close the turn consistently after a cancel: every pending call
        gets a result, and the model is told, in the history it will
        read next turn, that the user stopped it."""
        self._answer_pending_tool_calls(assistant_message, CANCELLED_TOOL_RESULT)
        emit("answer", CANCELLED_ANSWER)
        return CANCELLED_ANSWER

    def _stop_at_gate_cap(
        self, assistant_message: dict, object_name: str, count: int, outcome, emit
    ) -> str:
        """Stop the turn at the gate-failure cap (OT-16): render the
        object so the user sees what kept failing, answer the calls the
        model had queued, and say plainly what stopped."""
        sheet = self.dispatch(
            "render_views", {"object_name": object_name}, self.output_directory
        )
        for image_path in sheet.images:
            emit("render", str(image_path))
        self._answer_pending_tool_calls(assistant_message, GATE_CAP_TOOL_RESULT)
        last_gate = next(
            (gate for gate in outcome.gates if gate.get("object_name") == object_name), {}
        )
        verdict = last_gate.get("scene_state") or "; ".join(last_gate.get("gate_failures", ())) or outcome.stage_reached
        answer = GATE_CAP_ANSWER.format(
            object_name=object_name,
            count=count,
            cap=self.maximum_gate_failures_per_object,
            verdict=verdict,
        )
        emit("answer", answer)
        return answer
