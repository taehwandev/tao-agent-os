"""Constants for the shared Tao Graphify installation."""

from pathlib import Path


RUNTIME_TO_PLATFORM = {
    "agy": "antigravity",
    "antigravity": "antigravity",
    "claude": "claude",
    "codex": "codex",
}

# The active Tao Agent OS owns one bundled Graphify skill. Setup copies that
# bundle to the user-level runtime home; target repositories never own a skill
# copy or runtime discovery link.
RUNTIME_BUNDLED_SKILL_DIR = Path(".tao/skills/graphify")
GLOBAL_CANONICAL_SKILL_DIR = Path(".tao/skills/graphify")
GLOBAL_CANONICAL_SKILL_PATH = GLOBAL_CANONICAL_SKILL_DIR / "SKILL.md"

# Compatibility names are global-home relative. They must not be joined to a
# target project path.
CANONICAL_SKILL_DIR = GLOBAL_CANONICAL_SKILL_DIR
CANONICAL_SKILL_PATH = GLOBAL_CANONICAL_SKILL_PATH

GLOBAL_PLATFORM_SKILL_DIRS = {
    "agents": Path(".agents/skills/graphify"),
    "antigravity": Path(".gemini/config/skills/graphify"),
    "claude": Path(".claude/skills/graphify"),
    "codex": Path(".codex/skills/graphify"),
}

# Compatibility-only project maps for older callers. Production setup never
# creates these paths.
PLATFORM_SKILL_DIRS = {
    "agents": Path(".agents/skills/graphify"),
    "antigravity": Path(".agents/skills/graphify"),
    "claude": Path(".claude/skills/graphify"),
    "codex": Path(".codex/skills/graphify"),
}
PLATFORM_INTEGRATION_PATHS = {
    "agents": (),
    "antigravity": (),
    "claude": (),
    "codex": (),
}
TRACKING_POLICY_PATHS = (Path(".graphifyignore"),)

PROJECT_GRAPH_DIR = Path(".agents/local/graphify-out")
PROJECT_GRAPH_PATH = PROJECT_GRAPH_DIR / "graph.json"
PROJECT_MANIFEST_PATH = PROJECT_GRAPH_DIR / "manifest.json"

# These paths identify the removed project-bundle design. Their presence means
# setup has leaked common runtime assets into a target checkout.
PROJECT_RUNTIME_ASSET_PATHS = (
    Path(".tao/skills/graphify"),
    Path(".agents/skills/graphify"),
    Path(".agents/rules/graphify.md"),
    Path(".agents/workflows/graphify.md"),
    Path(".claude/skills/graphify"),
    Path(".codex/skills/graphify"),
)

GRAPHIFY_RUNTIME_ADAPTER_INPUTS = PROJECT_RUNTIME_ASSET_PATHS

GRAPHIFY_INPUT_BLOCK = "\n".join(
    (
        "# tao-graphify-inputs:start",
        ".tao/",
        ".agents/local/",
        "graphify-out/",
        "# tao-graphify-inputs:end",
    )
)
