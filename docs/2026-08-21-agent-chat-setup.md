# Chatting with the agent inside Blender

## 1. Pick a model

The agent's job is: write `bpy` Python, call tools, read measured gate
reports, and occasionally *look* at a contact sheet. That is a
coding-and-tools job first, vision second — the analyzer is the hard
gate, and VLM visual judgement is advisory (measured bias toward
accepting, with reliability that *degrades* as the generator improves).
So coding strength and tool discipline outrank raw vision quality.

| Use | Model | Why |
|---|---|---|
| **Default** | `kimi-k2.7-code` | Vision + tools + thinking, coding-tuned for long-horizon work, ~30% lower thinking-token usage — the latency that matters in chat. |
| Strongest | `kimi-k3` | Native multimodal agentic, highest ceiling. Pick when asset complexity beats turn latency. |
| Long sessions | `minimax-m3` | 1M context, native multimodality — whole build history stays in context. |
| Local, 24 GB | `qwen3.5:27b` | Vision + tools, fits a 3090 at 4-bit. Also a good cheap critic beside a stronger cloud writer. |
| Local, smaller | `gemma4:12b` | Leaves VRAM headroom for Blender itself. Weakest coding — expect more gate failures. |

Ruled out despite strong coding: `glm-5.2`, `deepseek-v4-pro`,
`minimax-m2.7`, `nemotron-3-*`, `gpt-oss` — **no vision**, so the agent
cannot look at its own work. Worth revisiting as the *writer* half of a
writer/critic split, with a small local vision model as the critic.

```sh
ollama pull kimi-k2.7-code     # or: ollama pull qwen3.5:27b
ollama serve
```

## 2. Install the addon

Blender → Edit → Preferences → Add-ons → Install… → pick
`blender_addon/__init__.py`, enable **"blended: Agent Chat"**.

In its preferences set:

- **blended repository** — the repo root (the folder containing `src/`)
- **Model** — e.g. `kimi-k2.7-code`
- **Endpoint** — `http://localhost:11434`, or `https://ollama.com` for Cloud
- **API key** — only for Cloud

## 3. Chat

Press **N** in the 3D viewport, open the **blended** tab. Type and Send.

Try: *"Build me a wooden crate, about 0.8 m, and show me the renders."*

## What you'll see

The transcript shows each step: the agent's thinking, each tool call,
the measured result, then its answer. The tools it has:

| Tool | What it does |
|---|---|
| `run_python` | Runs a chunk, then **gates** the named object. Its primary tool. |
| `inspect_object` | Re-measures an existing object without rebuilding. |
| `render_views` | Four-view contact sheet, returned as an image it can see. X-ray optional. |
| `search_ops` | Finds operations by keyword instead of guessing signatures. |
| `list_scene` | Bounded scene listing. |
| `export_asset` | Exports `.glb` and verifies by re-importing. |

## How it stays responsive

`bpy` is not thread-safe, but model calls block for seconds to minutes.
So the model call runs on a background thread, and **every tool call
that touches `bpy` is marshalled back to the main thread** via
`bpy.app.timers`. Nothing touches Blender off-thread; the UI never
freezes.

## What it will and won't do

It will refuse to call something finished because the render looks
good — the system prompt makes the ordering explicit: executed → passed
the gate → looks right, and all three are required. It reports
measurements rather than impressions, and escalates to you after three
honest failed attempts rather than looping.

The known limit: **the gate certifies structure, not intent.** A mesh
can be perfectly manifold and still be the wrong object — measured
here: a planter that passed every structural check with its drainage
hole sealed shut. That third check is yours and the agent's, from the
renders. Which is exactly why `render_views` exists and why the prompt
insists on it.
