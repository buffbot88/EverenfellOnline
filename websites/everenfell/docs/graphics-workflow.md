# Graphics workflow (mandatory for all client artwork)

No graphical task is finished until its result has been inspected inside
the actual running client. A passing build, a successful export, or a
typecheck proves nothing about appearance.

## The loop (every screen, every asset)

1. **Inspect the Flash reference** — artwork, hierarchy, placement,
   animation, styling (SWF bytes or contact sheets, never memory).
2. **Reconstruct or refine** — decoded geometry first; new art only
   where the product requires it (e.g. translated text).
3. **Render inside Phaser** — the real browser, real geometry,
   transparency, antialiasing, scaling.
4. **Capture and inspect** — full scene at gameplay resolution AND the
   native 935x512 logical composition; close-ups of edited elements.
5. **Compare → correct → verify again** — repeat until visual issues
   are resolved or explicitly documented as known gaps.

## Tool responsibilities

| Tool | Responsible for |
| --- | --- |
| Original Flash/SWF | Source of truth for artwork and composition |
| Ultima3D module | Procedural 3D construction and asset-generation operations it supports |
| Blender (5.2 LTS, headless) | Scene composition, typography, materials, lighting, transparent renders |
| PIL / image processing | Pixel-level cleanup, format conversion, small automated corrections |
| Phaser | Display and animation of the finished assets |

Rules: never 3D-ify authentic 2D art just to use a tool; new art
(translated text, embellishments) may use any pipeline leg that fits.
If a required tool is genuinely unavailable, report it as an
environment/tooling limitation — never silently substitute another
workflow. Ultima3D status in this environment: inspected (geometry-only
builders, zero text/texture ops in its worker, no MCP client to operate
its protocol); Blender 5.2.2 LTS drives headless via
`scripts/blender/render_title.py` (proven: beveled metallic "CREATE",
transparent PNG). PIL remains the default for 2D recovery; Blender for
dimensional hero text and future embellishments.

## Completion reports must carry evidence

- Original reference: which Flash asset or decoded structure was used.
- Final image: screenshot of the running scene (not the exported PNG).
- Visual differences: what remains inaccurate or weak.
- Tool provenance: which tool actually produced each asset.
- Verification: what was personally inspected, what remains untested.

Status wording: if the client could not be launched (process rule),
the status is **implemented, awaiting visual verification** — never
finished. One-and-done per screen still holds: no placeholder
translations on screens being actively rebuilt.
