"""The chat panel's UX contract, as assertions.

Decision D7 of `docs/2026-09-05-chat-ux-overhaul-plan.md`: "best-in-class"
is only a claim if it is measured, so the heuristics the overhaul was
designed against are executable here rather than argued in a document.

Each test names the heuristic it defends:

* **H-LAN** — match the design language of the host environment, undo and
  redo included, through the host's own front-end UI APIs
  (DOI 10.1080/10447318.2026.2632170).
* **EID** — do not force processing to a higher cognitive level than the
  task demands; support all three levels at once (DOI 10.1109/21.156574).
* **Plan-as-shared-representation** — a plan of natural-language steps
  with a progress bar over them, not an approval gate
  (DOI 10.48550/arXiv.2507.22358, with DOI 10.48550/arxiv.2604.14228 on
  why the gate would be rubber-stamped).
* **Reference pairing** — a candidate render shown beside a reference,
  which is what recovers a reviewer's recall
  (DOI 10.48550/arXiv.2604.11082).
* **Hotkey rehearsal** — print the binding on the control
  (DOI 10.1145/2470654.2470735).
"""

from __future__ import annotations

import types
from pathlib import Path

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender")

pytestmark = pytest.mark.blender

from test_addon_draw import (  # noqa: E402
    _draw,
    _draw_all,
    _load_addon,
    _make_context,
)

from blended.agent.plan import TurnPlan  # noqa: E402

PLAN_STEPS = ("Build the crate body", "Add the slats", "Render and verify")
STUB_ICON_IDENTIFIER = 4242
# Labels the pinned surface draws besides the answer's own rows: the
# bubble header, the status line, the settings header and the model
# name. Counted, not guessed — the assertion is about the ANSWER not
# growing, so the chrome has to be allowed for explicitly.
_ROWS_OF_CHROME_AROUND_AN_ANSWER = 6


def _labels(emitted):
    return [text for kind, text, _ in emitted if kind == "label"]


def _operator_handles(emitted, idname):
    return [handle for kind, name, handle in emitted if kind == "operator" and name == idname]


def test_the_plan_and_its_progress_are_drawn_whenever_a_plan_exists():
    """Plan-as-shared-representation: the steps the agent committed to,
    verbatim, with Blender's own progress bar over them."""
    module = _load_addon("blended_heuristics_plan")
    module._STATE.plan = TurnPlan(steps=PLAN_STEPS, current_step=2)
    module._STATE.busy = True
    emitted = _draw(module, _make_context("blended_heuristics_plan"))

    labels = _labels(emitted)
    for number, step_text in enumerate(PLAN_STEPS, start=1):
        assert f"{number}. {step_text}" in labels, "every step must be shown verbatim"
    progress = [(text, factor) for kind, text, factor in emitted if kind == "progress"]
    assert progress == [("step 2/3", pytest.approx(2 / 3))], (
        "the progress bar must be Blender's own widget and must report "
        "the step the agent says it is on"
    )


def test_a_finished_plan_never_claims_a_step_the_agent_did_not_reach():
    """A progress display that rounds up is a lie the user cannot see
    through: after the turn, only steps the agent reported reaching may
    read as done."""
    module = _load_addon("blended_heuristics_honest")
    module._STATE.plan = TurnPlan(steps=PLAN_STEPS, current_step=1)
    module._STATE.busy = False
    emitted = _draw(module, _make_context("blended_heuristics_honest"))

    factors = [factor for kind, _, factor in emitted if kind == "progress"]
    assert factors == [pytest.approx(1 / 3)]
    assert module._STATE.plan.status_text() == "step 1/3"


def test_a_finished_plan_gives_its_rows_back_to_the_answer():
    """The step list is what a user watches WHILE the agent works. After
    the turn it is competing for rows with the answer they are actually
    reading, in a sidebar that measured 27 rows total — so it collapses
    to its header and bar on the working surface, and the record keeps
    every step."""
    module = _load_addon("blended_heuristics_collapse")
    module._STATE.plan = TurnPlan(steps=PLAN_STEPS, current_step=3)
    module._STATE.transcript = [
        ("plan", '{"steps": ' + str(list(PLAN_STEPS)).replace("'", '"') + ', "current_step": 3}'),
        ("answer", "Done."),
    ]
    context = _make_context("blended_heuristics_collapse")

    module._STATE.busy = True
    working = _labels(_draw(module, context))
    module._STATE.busy = False
    finished = _labels(_draw(module, context))

    assert f"1. {PLAN_STEPS[0]}" in working, "steps must be visible while working"
    assert f"1. {PLAN_STEPS[0]}" not in finished, (
        "a finished plan must not spend rows on steps the user has "
        "already watched go by"
    )
    assert "Plan" in finished, "the plan header and its bar stay"
    assert [factor for kind, _, factor in _draw(module, context) if kind == "progress"]

    record = _labels(_draw(module, context, panel=module.BLENDED_PT_history))
    assert f"1. {PLAN_STEPS[0]}" in record, "the record keeps every step"


def test_the_answer_budget_comes_from_the_region_not_a_guess():
    """The measured sidebar: 1104 px at ui_scale 2.0 is 27 rows, which
    is why three successive "generous" caps still lost the prompt box.
    The budget subtracts what is actually drawn around the answer, and
    never returns less than the floor."""
    module = _load_addon("blended_heuristics_budget")
    sidebar_rows = 27

    bare = module._answer_row_budget(
        1104, 2.0, plan_step_count=0, has_plan=False, has_renders=False
    )
    assert bare == sidebar_rows - module._COMPOSER_RESERVED_ROWS

    # The state a reviewer actually reads in: turn finished, so the plan
    # is collapsed to two rows and the renders are up.
    finished = module._answer_row_budget(
        1104, 2.0, plan_step_count=0, has_plan=True, has_renders=True
    )
    assert finished == bare - module._RENDER_CARD_ROWS - module._PLAN_CARD_FIXED_ROWS
    assert finished > module._MINIMUM_ANSWER_ROWS, (
        "a finished turn must leave the answer more than the floor: "
        "that is the moment the answer is the whole point"
    )

    # Mid-turn with a long plan there genuinely are not enough rows, and
    # the floor — not a negative number — is what the answer gets.
    working = module._answer_row_budget(
        1104, 2.0, plan_step_count=5, has_plan=True, has_renders=True
    )
    assert working == module._MINIMUM_ANSWER_ROWS

    # A tiny sidebar cannot go negative; a huge one is bounded only by
    # its own height.
    assert (
        module._answer_row_budget(
            120, 2.0, plan_step_count=8, has_plan=True, has_renders=True
        )
        == module._MINIMUM_ANSWER_ROWS
    )
    assert (
        module._answer_row_budget(
            4000, 1.0, plan_step_count=0, has_plan=False, has_renders=False
        )
        > bare
    )


def test_no_plan_means_no_plan_card():
    """The card is evidence, not chrome: with nothing declared there is
    nothing to show, and the composer must not be pushed down by an
    empty box."""
    module = _load_addon("blended_heuristics_noplan")
    module._STATE.plan = None
    emitted = _draw(module, _make_context("blended_heuristics_noplan"))

    assert "Plan" not in _labels(emitted)
    assert not [kind for kind, _, _ in emitted if kind == "progress"]


def test_renders_are_shown_as_a_pair_each_with_a_way_to_enlarge_it():
    """Reference pairing: the newest render beside the one before it.
    The Open button is unconditional — the thumbnail is the nice case,
    not the only case, because a headless or preview-less Blender still
    has to let the user see the file."""
    module = _load_addon("blended_heuristics_renders")
    module._STATE.transcript = [
        ("render", "/tmp/blended/crate_sheet_1.png"),
        ("answer", "Here it is."),
        ("render", "/tmp/blended/crate_sheet_2.png"),
    ]
    emitted = _draw(module, _make_context("blended_heuristics_renders"))

    labels = _labels(emitted)
    assert "before" in labels and "now" in labels, (
        "an unlabelled pair of pictures cannot be compared"
    )
    paths = [handle.path for handle in _operator_handles(emitted, "blended.show_render")]
    assert paths.count("/tmp/blended/crate_sheet_2.png") >= 1
    assert paths.count("/tmp/blended/crate_sheet_1.png") >= 1


def test_a_thumbnail_is_drawn_when_a_preview_is_available():
    """The picture itself: `template_icon` is Blender's own image widget
    (H-LAN). Previews need a window, so the collection is stubbed —
    what is asserted is that the panel USES the icon it is given."""
    module = _load_addon("blended_heuristics_thumbnail")
    module._STATE.transcript = [("render", "/tmp/blended/crate_sheet.png")]
    module._PREVIEWS = types.SimpleNamespace(
        icon_for=lambda path: STUB_ICON_IDENTIFIER
    )
    emitted = _draw(module, _make_context("blended_heuristics_thumbnail"))

    icons = [value for kind, value, _ in emitted if kind == "template_icon"]
    assert STUB_ICON_IDENTIFIER in icons


def test_a_missing_preview_collection_still_draws_the_panel():
    """`draw()` must never raise: an exception inside it makes Blender
    silently abandon the rest of the panel, so a broken preview
    collection may cost the picture and nothing else."""
    module = _load_addon("blended_heuristics_broken_preview")
    module._STATE.transcript = [("render", "/tmp/blended/crate_sheet.png")]

    def _explode(path):
        raise RuntimeError("no preview for you")

    module._PREVIEWS = types.SimpleNamespace(icon_for=_explode)
    emitted = _draw(module, _make_context("blended_heuristics_broken_preview"))

    assert not [kind for kind, _, _ in emitted if kind == "template_icon"]
    assert [kind for kind, name, _ in emitted if kind == "textbox"], (
        "the composer must still draw when a thumbnail cannot"
    )


def test_the_scene_the_agent_was_given_is_shown_next_to_the_prompt():
    """Selection is sent with every prompt (D3), so the user has to be
    able to see WHAT was sent — silent context is the kind of hidden
    input that makes an agent look unpredictable."""
    module = _load_addon("blended_heuristics_context")
    module._STATE.transcript = [
        ("user", "make this taller"),
        ("context", "active=Crate 0.60×0.40×0.50 m | selected: Crate | OBJECT"),
    ]
    emitted = _draw_all(module, _make_context("blended_heuristics_context"))

    labels = _labels(emitted)
    assert any("active=Crate" in text for text in labels)
    assert "make this taller" in labels


def test_progress_events_never_enter_the_conversation():
    """`step` events move the plan card. Drawn as messages they would be
    one grey row per tool call, which is the wall of traffic this
    overhaul exists to remove."""
    module = _load_addon("blended_heuristics_steps")
    module._STATE.transcript = [
        ("user", "Build a crate"),
        ("step", "1"),
        ("step", "2"),
        ("answer", "Built it."),
    ]
    emitted = _draw_all(module, _make_context("blended_heuristics_steps"))

    labels = _labels(emitted)
    assert "1" not in labels and "2" not in labels
    assert "Built it." in labels


def test_revert_is_live_after_a_turn_and_dead_while_one_runs():
    """H-LAN, undo parity: the turn is one undo step, and the button
    that says so is present at all times so its state can teach — live
    when there is a turn to revert, greyed while the agent works."""
    module = _load_addon("blended_heuristics_revert")
    context = _make_context("blended_heuristics_revert")

    def _revert_row_enabled(emitted):
        """The enabled flag written immediately before the revert
        operator is drawn — the row that owns it."""
        states = [
            value
            for index, (kind, value, _) in enumerate(emitted)
            if kind == "enabled"
            and any(
                later_kind == "operator" and later_name == "blended.revert_turn"
                for later_kind, later_name, _ in emitted[index : index + 2]
            )
        ]
        assert len(states) == 1, "exactly one row must own the revert button"
        return states[0]

    module._STATE.can_revert = False
    module._STATE.busy = False
    assert _revert_row_enabled(_draw(module, context)) is False

    module._STATE.can_revert = True
    after_turn = _draw(module, context)
    assert _revert_row_enabled(after_turn) is True
    assert "Ready" in _labels(after_turn)

    module._STATE.busy = True
    during_turn = _draw(module, context)
    assert _revert_row_enabled(during_turn) is False, (
        "reverting mid-turn would undo work the agent is still building on"
    )
    assert "Ready" not in _labels(during_turn)


def test_the_send_button_prints_its_own_hotkey():
    """Hotkey rehearsal: a binding nobody can see is a binding nobody
    learns (DOI 10.1145/2470654.2470735). The keymap binds Cmd/Ctrl+Enter
    to `blended.send_message`; the button has to say so."""
    module = _load_addon("blended_heuristics_hotkey")
    module._STATE.busy = False
    emitted = _draw(module, _make_context("blended_heuristics_hotkey"))

    assert _operator_handles(emitted, "blended.send_message"), (
        "the send operator must be drawn when idle"
    )
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "Send   ⌘⏎" in source, (
        "the binding must be printed on the button, not only bound in the keymap"
    )


def test_the_working_surface_does_not_grow_with_the_turn():
    """The measured failure this overhaul fixes: one finished turn
    pushed the plan, the renders and the composer off the bottom of the
    sidebar (live GUI screenshot, 2026-09-05). A Blender region cannot
    be scrolled from code, so the fix is structural — the working
    surface must be a BOUNDED number of rows no matter how long the
    turn was."""
    module = _load_addon("blended_heuristics_offscreen")
    short_turn = [("user", "Build a crate"), ("answer", "Built it.")]
    long_turn = (
        [("user", "Build a crate")]
        + [("tool", 'run_python({"source": "x", "object_name": "Crate"})')] * 15
        + [("result", "OK: Crate\n  gate: PASS")] * 15
        + [("thinking", "considering the slats")] * 5
        + [("answer", "Built it.")]
    )
    context = _make_context("blended_heuristics_offscreen")
    module._STATE.transcript = short_turn
    small = _draw(module, context)
    module._STATE.transcript = long_turn
    large = _draw(module, context)

    assert len(large) == len(small), (
        "a 36-event turn drew a different number of widgets than a "
        "2-event turn: the working surface is growing with the "
        "conversation again"
    )

    # …and neither may an unbounded ANSWER grow it: the model decides
    # how long its reply is, so the surface caps it and points at the
    # record.
    module._STATE.transcript = [
        ("user", "Build a crate"),
        ("answer", "\n".join(f"finding number {n}" for n in range(60))),
    ]
    long_answer = _draw(module, context)
    labels = _labels(long_answer)
    assert "finding number 0" in labels
    assert "finding number 59" not in labels
    assert any("more lines — open Conversation" in text for text in labels), (
        "a truncated answer must say so and say where the rest is"
    )
    budget = module._answer_row_budget(
        1104, 1.0, plan_step_count=0, has_plan=False, has_renders=False
    )
    assert len(labels) <= budget + _ROWS_OF_CHROME_AROUND_AN_ANSWER, (
        "the capped answer must fit the budget the region actually has"
    )
    assert "textbox" in [kind for kind, _, _ in long_answer]

    # The record still holds every word.
    record = _labels(_draw(module, context, panel=module.BLENDED_PT_history))
    assert "finding number 59" in record
