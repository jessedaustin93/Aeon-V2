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
