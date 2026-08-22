"""The agent loop against real bpy, with a scripted model.

The model is stubbed so the LOOP is what's under test: does it dispatch
tools, attach rendered images, feed results back, and terminate.
"""

import pytest

bpy = pytest.importorskip("bpy", reason="requires Blender-as-module (pip install bpy)")
pytest.importorskip("PIL.Image", reason="contact sheets require Pillow")

pytestmark = pytest.mark.blender

BUILD_SOURCE = """
from blended.ops import add_box, link_into_scene
crate = add_box("ChatCrate", 0.6, 0.6, 0.6)
link_into_scene(crate)
"""


class ScriptedClient:
    """Replays a fixed list of assistant messages.

    Configured single-model (no separate eye) so these tests exercise
    the direct image-attachment path; the writer/eye split has its own
    tests below.
    """

    def __init__(self, replies):
        import dataclasses

        from blended.agent import ModelConfig

        self.replies = list(replies)
        self.seen_messages = []
        self.config = dataclasses.replace(
            ModelConfig.from_environment(),
            model="vision-writer",
            vision_model="",
        )

    def chat(self, messages, tools=None):
        self.seen_messages.append(list(messages))
        return self.replies.pop(0)


@pytest.fixture()
def empty_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    yield


def test_loop_runs_a_tool_then_answers(empty_scene, tmp_path):
    from blended.agent import AgentSession

    client = ScriptedClient([
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_python", "arguments": {
                "source": BUILD_SOURCE, "object_name": "ChatCrate"}}}
        ]},
        {"role": "assistant", "content": "Built ChatCrate — gate passed."},
    ])
    session = AgentSession(client=client, output_directory=tmp_path)

    answer = session.send("Make me a crate.")

    assert "gate passed" in answer
    assert "ChatCrate" in bpy.data.objects
    # The tool result was fed back to the model as a tool message.
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    assert "GATE: PASS" in tool_messages[0]["content"] or "gate: PASS" in tool_messages[0]["content"]


def test_render_result_attaches_an_image_the_model_can_see(empty_scene, tmp_path):
    from blended.agent import AgentSession

    client = ScriptedClient([
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_python", "arguments": {
                "source": BUILD_SOURCE, "object_name": "ChatCrate"}}}
        ]},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "render_views",
                          "arguments": {"object_name": "ChatCrate"}}}
        ]},
        {"role": "assistant", "content": "Looks like a crate."},
    ])
    session = AgentSession(client=client, output_directory=tmp_path)
    session.send("Make a crate and show me.")

    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    render_message = tool_messages[-1]
    assert "images" in render_message, "the model was told to look but got no image"
    assert len(render_message["images"]) == 1
    assert len(render_message["images"][0]) > 1000  # real base64 payload


def test_gate_failure_is_reported_to_the_model(empty_scene, tmp_path):
    from blended.agent import AgentSession

    open_box_source = """
import bmesh
from blended.ops import add_box, link_into_scene
box = add_box("BadCrate", 0.5, 0.5, 0.5)
link_into_scene(box)
w = bmesh.new(); w.from_mesh(box.data)
w.faces.ensure_lookup_table(); w.faces.remove(w.faces[0])
w.to_mesh(box.data); w.free()
"""
    client = ScriptedClient([
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_python", "arguments": {
                "source": open_box_source, "object_name": "BadCrate"}}}
        ]},
        {"role": "assistant", "content": "The gate rejected it — it's open."},
    ])
    session = AgentSession(client=client, output_directory=tmp_path)
    session.send("Make a crate.")

    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert "boundary edges" in tool_messages[0]["content"]


def test_tool_exception_is_surfaced_not_swallowed(empty_scene, tmp_path):
    from blended.agent import AgentSession

    client = ScriptedClient([
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "inspect_object",
                          "arguments": {"object_name": "DoesNotExist"}}}
        ]},
        {"role": "assistant", "content": "That object isn't in the scene."},
    ])
    session = AgentSession(client=client, output_directory=tmp_path)
    session.send("Inspect DoesNotExist.")

    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert "No object named" in tool_messages[0]["content"]


def test_runaway_tool_calling_is_capped(empty_scene, tmp_path):
    from blended.agent import AgentSession

    looping_reply = {"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "list_scene", "arguments": {}}}
    ]}
    client = ScriptedClient([looping_reply] * 30)
    session = AgentSession(
        client=client, output_directory=tmp_path, maximum_tool_calls_per_turn=4
    )
    answer = session.send("Loop forever.")
    assert "Stopped after 4 tool calls" in answer


def test_search_ops_finds_operations_without_guessing(empty_scene, tmp_path):
    from blended.agent.tools import dispatch_tool

    result_text, images = dispatch_tool("search_ops", {"query": "boolean"}, tmp_path)
    assert "boolean_union" in result_text
    assert images == []

    miss_text, _ = dispatch_tool("search_ops", {"query": "zzzz"}, tmp_path)
    assert "No operation matches" in miss_text


def test_export_tool_verifies_the_written_file(empty_scene, tmp_path):
    from blended.agent.tools import dispatch_tool
    from blended.builders import CrateBuilder, CrateParameters

    CrateBuilder(CrateParameters(name="ExportMe")).build()
    result_text, _ = dispatch_tool(
        "export_asset",
        {"object_name": "ExportMe", "path": str(tmp_path / "crate.glb")},
        tmp_path,
    )
    assert "Exported and verified" in result_text
    assert (tmp_path / "crate.glb").exists()


# --- the writer/eye split --------------------------------------------------


class TwoModelClient:
    """Records which model each call went to, so routing is verifiable."""

    def __init__(self, config, writer_replies, eye_reply="A wooden crate, evenly proportioned."):
        self.config = config
        self.writer_replies = list(writer_replies)
        self.eye_reply = eye_reply
        self.calls: list[tuple[str, bool]] = []  # (model, had_images)

    def chat(self, messages, tools=None):
        had_images = any("images" in message for message in messages)
        self.calls.append((self.config.model, had_images))
        if self.config.model == "eye-model":
            return {"role": "assistant", "content": self.eye_reply}
        return self.writer_replies.pop(0)


def _split_config():
    from blended.agent import ModelConfig
    import dataclasses

    return dataclasses.replace(
        ModelConfig.from_environment(),
        model="writer-model",
        vision_model="eye-model",
    )


def test_writer_never_receives_raw_images(empty_scene, tmp_path, monkeypatch):
    """deepseek-v4-flash is text-only — handing it image bytes is a bug."""
    from blended.agent import AgentSession
    import blended.agent.loop as loop_module

    config = _split_config()
    client = TwoModelClient(config, [
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_python", "arguments": {
                "source": BUILD_SOURCE, "object_name": "ChatCrate"}}}
        ]},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "render_views", "arguments": {
                "object_name": "ChatCrate", "look_for": "is it square?"}}}
        ]},
        {"role": "assistant", "content": "Built and checked."},
    ])
    # The eye builds its own client from the same config; point it here.
    monkeypatch.setattr(loop_module, "OllamaClient", lambda cfg: TwoModelClient(
        cfg, [], eye_reply="A cube-shaped crate, square in all views."
    ))

    session = AgentSession(client=client, output_directory=tmp_path)
    session.send("Make a crate and look at it.")

    # No message anywhere in the writer's history carries image data.
    assert not any("images" in message for message in session.messages), (
        "raw images leaked into a text-only writer's context"
    )
    # But the description DID reach it.
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert "what the render shows" in tool_messages[-1]["content"]
    assert "square in all views" in tool_messages[-1]["content"]


def test_eye_failure_degrades_without_killing_the_turn(empty_scene, tmp_path, monkeypatch):
    from blended.agent import AgentSession
    import blended.agent.loop as loop_module

    def exploding_client(cfg):
        raise RuntimeError("eye endpoint unreachable")

    config = _split_config()
    client = TwoModelClient(config, [
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_python", "arguments": {
                "source": BUILD_SOURCE, "object_name": "ChatCrate"}}}
        ]},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "render_views",
                          "arguments": {"object_name": "ChatCrate"}}}
        ]},
        {"role": "assistant", "content": "Gate passed; could not see the render."},
    ])
    monkeypatch.setattr(loop_module, "OllamaClient", exploding_client)

    session = AgentSession(client=client, output_directory=tmp_path)
    answer = session.send("Make a crate and look at it.")

    assert answer  # the turn still completed
    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert "working blind" in tool_messages[-1]["content"]


def test_single_model_mode_still_attaches_images(empty_scene, tmp_path):
    """With a vision-capable writer and no separate eye, images go
    straight into the conversation as before."""
    from blended.agent import AgentSession, ModelConfig
    import dataclasses

    config = dataclasses.replace(
        ModelConfig.from_environment(), model="vision-writer", vision_model=""
    )
    client = TwoModelClient(config, [
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "run_python", "arguments": {
                "source": BUILD_SOURCE, "object_name": "ChatCrate"}}}
        ]},
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "render_views",
                          "arguments": {"object_name": "ChatCrate"}}}
        ]},
        {"role": "assistant", "content": "Looks right."},
    ])
    session = AgentSession(client=client, output_directory=tmp_path)
    session.send("Make a crate and look.")

    tool_messages = [m for m in session.messages if m.get("role") == "tool"]
    assert "images" in tool_messages[-1]
