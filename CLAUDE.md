## Rules for the agent building the harness
- Plan-then-execute — Every harness task starts with a written plan (components, files, verification steps). The plan becomes the checklist. No emergent design mid-build.  _Always_ consult home still when planning.  It's an academic search engine with semantic search. Ensure to include DOI reference in comments to guide other agents on relook up.
- Ensure large assets and artifacts are kept in an `outputs/` folder and are gitignored
- Use `snake_case` wherever possible
- Small chunks — Implement and verify in small steps. Never emit one large script or one large file in a single move.
- Verify mutations — State the expected effect before any mutating change; prefer small, reversible steps. Snapshot before irreversible operations.
- Validation gates — A step is not done until its assertions pass. Never report progress on a failed check.
- Fail loud — Fix failures before moving on. Never paper over or note-for-later; cap rebuild attempts, then surface the failure with the full log.
- Pin verified behavior — After the user signs off on a behavior in the viewport, capture it as a regression test immediately, without asking.
- Mistake memory — After every fix, capture error + cause + fix. Carry this forward across sessions so the same mistake never recurs.
- One path — One execution path per feature. No fallbacks, no stubs, no legacy branches. When the primary path fails, fail loudly.

## Rules for how the harness should be coded
- One class per part — Every object/assembly is a class owning its Blender objects, exposing named build steps. No flat top-to-bottom scripts.
- Compose from sub-builders — Assemblies compose sub-builders; build and validate at the same granularity so one bug can't poison diagnosis of the whole.
- Config separate from construction — All parameters live in a serializable config dataclass; construction code never defines values.
- No magic numbers — No literals in construction or validation. Every dimension, count, angle, and tolerance is a named constant in config.
- Units in names — Suffix quantities with _m, _deg, _rad; prefer waist_xy over xy. Never convert units implicitly.
- Named tolerances — Assertions reference tolerance constants from config, never inline numbers.
- Validation = assertions — Steps and tests are assertions executed in the scene; a step isn't complete until they pass.
- Minimum checks, always — Every step asserts: objects exist by name, dimensions within tolerance, finite transforms, materials assigned, no stray objects.
- Whitelisted builder API — Expose only sanctioned builder calls through the facade; no raw bpy from the caller. The harness is the only way to build.
- Two-stage critique — Deterministic geometry gate first, visual/render critique second. Never spend visual tokens on scenes that fail bounds.
- Terminal states — Every step declares its terminal state (names, dims, dependencies); the next step's precondition is the previous step's asserted terminal state.
- Assert frames — Every assembly declares its origin and frame; coordinate transforms are asserted, not assumed.
- Golden snapshots — Sign-off stores render, parameter snapshot, and regression test together; the harness detects drift against them.
- Pin the API — Carries version-pinned API docs in the package; execution errors route back through the same doc lookup. The harness owns the version contract.
- Feedback as deltas — Report object lists before/after, changed transforms, errors with line refs. Concise, never dumps.
- Mistake memory in-package — Maintain a curated failures log inside the package; successful fixes append error + fix + the assertion that guards it.
