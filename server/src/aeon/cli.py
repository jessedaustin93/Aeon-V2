"""Aeon-V2 command-line entry points."""
import argparse
from pathlib import Path

from .core.config import Config
from .skills.store import SkillStore, _NAME_RE, _parse_skill_md, _serialize_skill, Skill, PROPOSALS_DIR

# Mirrors aeon-v1's memory/ layout (see aeon-v1/memory/README.md).
MEMORY_SUBDIRS = [
    "raw",
    "episodic",
    "semantic",
    "reflections",
    "consolidations",
    "media/uploads",
    "logs",
    "staging",
    "approved",
    "schemas",
    "tool_additions",
]

TOP_LEVEL_DIRS = ["vault", "skills", "research"]

DEFAULT_RUNTIME_SKILLS = [
    Skill(
        name="local-model-awareness",
        description="Identify Aeon's current local model routing before answering model identity questions",
        body=(
            "Use this skill whenever Jesse asks what model you are, what LLM is "
            "running, whether you are Claude, or why a response sounds like a "
            "different model family.\n\n"
            "1. Treat Aeon's identity and the runtime model as separate facts: "
            "Aeon is the assistant/runtime; the model is the currently routed "
            "local or OpenAI-compatible worker behind a role.\n"
            "2. Call `model_status` before naming a specific model, model family, "
            "worker, or endpoint.\n"
            "3. State plainly that Aeon is not Claude, not Anthropic, and not in "
            "the Claude model family.\n"
            "4. Report the configured role map and selected worker from the tool "
            "result. If a worker is unhealthy or the loaded model list is empty, "
            "say that instead of guessing.\n"
            "5. Do not infer model family from writing style or training behavior."
        ),
    ),
    Skill(
        name="designated-model-routing",
        description="Route designated subtasks to the configured chat or deep model role",
        body=(
            "Use this skill when a task explicitly designates another model role "
            "or when a subtask is better handled by a separate role such as `deep` "
            "for careful reasoning or `chat` for fast drafting.\n\n"
            "1. Call `model_status` if you need to confirm available roles or "
            "workers before delegating.\n"
            "2. Use `model_delegate` for bounded, tool-less subtasks only. Include "
            "the requested role, a concrete prompt, and a short system instruction "
            "when it improves the result.\n"
            "3. Keep file access, shell actions, web access, memory writes, and "
            "approval-gated actions in the main Aeon loop; delegated model calls "
            "must not be treated as having used tools.\n"
            "4. Merge delegated output into your answer with the role/model/worker "
            "metadata when it matters. Do not hide errors or unhealthy workers.\n"
            "5. Prefer the configured `deep` role for analysis, critique, or long "
            "reasoning. Prefer the configured `chat` role for fast phrasing, "
            "summaries, and simple alternatives."
        ),
    ),
    Skill(
        name="ssh-machine-checks",
        description="Use approval-gated SSH for checks on Jesse's configured lab machines",
        body=(
            "Use this skill when Jesse asks you to inspect another machine such as "
            "T3610, T5810B, X1, HP, or any configured SSH alias.\n\n"
            "1. Prefer local tools for the Aeon server itself. For another machine, "
            "use `ssh_run` with a configured host alias.\n"
            "2. `ssh_run` is approval-gated. Explain the exact host and command "
            "needed, then wait for approval instead of claiming you lack access.\n"
            "3. Use read-only commands for checks unless Jesse explicitly requests "
            "a change. Examples: `hostname`, `systemctl --user status NAME`, "
            "`docker ps`, `docker logs --tail 100 NAME`, `find`, and service "
            "or app-specific status commands.\n"
            "4. If a host alias is rejected, call out that the alias is missing "
            "from `AEON_SSH_HOSTS` or the server's `~/.ssh/config`.\n"
            "5. Summarize the remote command output and include errors plainly."
        ),
    ),
]


def init_data(argv: list[str] | None = None) -> int:
    """Scaffold the Aeon data root (memory tree, vault mirror, skills, research)."""
    parser = argparse.ArgumentParser(
        prog="aeon-init-data",
        description="Create the Aeon-V2 data directory tree at AEON_DATA_DIR (or --root).",
    )
    parser.add_argument("--root", type=Path, default=None, help="Override AEON_DATA_DIR")
    args = parser.parse_args(argv)

    config = Config(base_path=args.root) if args.root else Config()
    root = config.base_path
    for sub in MEMORY_SUBDIRS:
        (root / "memory" / sub).mkdir(parents=True, exist_ok=True)
    for top in TOP_LEVEL_DIRS:
        (root / top).mkdir(parents=True, exist_ok=True)
    print(f"Aeon data root ready: {root.resolve()}")
    return 0


def _skill_defect(skill_dir: Path) -> str | None:
    """Return None if the skill dir holds a valid SKILL.md, else the defect."""
    md = skill_dir / "SKILL.md"
    if not md.is_file():
        return "no SKILL.md"
    parsed = _parse_skill_md(md.read_text(encoding="utf-8"))
    if parsed is None:
        return "missing frontmatter or name/description"
    name = parsed["meta"]["name"]
    if not _NAME_RE.match(name):
        return f"invalid name '{name}' (need lowercase letters/digits/hyphens)"
    if name != skill_dir.name:
        return f"name '{name}' does not match folder '{skill_dir.name}'"
    return None


def lint_skills(argv: list[str] | None = None) -> int:
    """Validate every SKILL.md so hand-authoring failures stop being silent."""
    parser = argparse.ArgumentParser(
        prog="aeon-lint-skills",
        description="Validate all skills under AEON_DATA_DIR/skills (active + proposals).",
    )
    parser.add_argument("--root", type=Path, default=None, help="Override AEON_DATA_DIR")
    args = parser.parse_args(argv)
    config = Config(base_path=args.root) if args.root else Config()
    skills_root = config.base_path / "skills"

    dirs: list[tuple[str, Path]] = []
    if skills_root.is_dir():
        for entry in sorted(skills_root.iterdir()):
            if entry.is_dir() and entry.name != PROPOSALS_DIR:
                dirs.append(("active", entry))
        proposals = skills_root / PROPOSALS_DIR
        if proposals.is_dir():
            for entry in sorted(proposals.iterdir()):
                if entry.is_dir():
                    dirs.append(("proposal", entry))

    if not dirs:
        print("No skills found.")
        return 0

    bad = 0
    for kind, d in dirs:
        defect = _skill_defect(d)
        if defect:
            bad += 1
            print(f"FAIL [{kind}] {d.name}: {defect}")
        else:
            print(f"ok   [{kind}] {d.name}")
    print(f"\n{len(dirs) - bad}/{len(dirs)} valid.")
    return 1 if bad else 0


def add_skill(argv: list[str] | None = None) -> int:
    """Scaffold a well-formed skill (active, or a proposal for UI review)."""
    parser = argparse.ArgumentParser(
        prog="aeon-add-skill",
        description="Create a valid SKILL.md under AEON_DATA_DIR/skills.",
    )
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument("--body", default=None, help="Skill body (markdown steps)")
    parser.add_argument("--body-file", type=Path, default=None, help="Read body from a file")
    parser.add_argument("--proposal", action="store_true", help="Place under _proposals/ for UI review")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing skill")
    parser.add_argument("--root", type=Path, default=None)
    args = parser.parse_args(argv)

    if not _NAME_RE.match(args.name):
        print(f"error: invalid name '{args.name}' (lowercase letters, digits, hyphens; <=64 chars)")
        return 2
    body = args.body
    if args.body_file:
        body = args.body_file.read_text(encoding="utf-8")
    if not body or not body.strip():
        print("error: provide --body or --body-file with content")
        return 2

    config = Config(base_path=args.root) if args.root else Config()
    store = SkillStore(config)
    target_root = store.proposals_root if args.proposal else store.root
    target = target_root / args.name
    md = target / "SKILL.md"
    if md.exists() and not args.force:
        print(f"error: {md} already exists (use --force to overwrite)")
        return 1
    target.mkdir(parents=True, exist_ok=True)
    md.write_text(
        _serialize_skill(Skill(name=args.name, description=args.description, body=body)),
        encoding="utf-8",
    )
    where = "proposal (approve it in the Skills panel)" if args.proposal else "active"
    print(f"Wrote {where} skill: {md}")
    return 0


def seed_runtime_skills(argv: list[str] | None = None) -> int:
    """Install Aeon's default operational skills into the active skill set."""
    parser = argparse.ArgumentParser(
        prog="aeon-seed-runtime-skills",
        description="Install default Aeon operational skills into AEON_DATA_DIR/skills.",
    )
    parser.add_argument("--root", type=Path, default=None, help="Override AEON_DATA_DIR")
    parser.add_argument("--force", action="store_true", help="Overwrite existing seeded skills")
    args = parser.parse_args(argv)

    config = Config(base_path=args.root) if args.root else Config()
    store = SkillStore(config)
    written = 0
    skipped = 0
    for skill in DEFAULT_RUNTIME_SKILLS:
        target = store.root / skill.name / "SKILL.md"
        if target.exists() and not args.force:
            skipped += 1
            print(f"skip existing skill: {target}")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_serialize_skill(skill), encoding="utf-8")
        written += 1
        print(f"wrote runtime skill: {target}")
    print(f"{written} written, {skipped} skipped.")
    return 0
