"""Skill storage.

Layout (agentskills.io):
    <data>/skills/<name>/SKILL.md            — active skills
    <data>/skills/_proposals/<name>/SKILL.md — proposed, awaiting approval

SKILL.md = YAML frontmatter (flat key: value pairs) + markdown body.
Proposals never load into the agent until approved.
"""
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from aeon.core.config import Config

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)

PROPOSALS_DIR = "_proposals"


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: str = ""


def _parse_skill_md(text: str) -> Optional[dict]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return None
    meta = {}
    for line in match.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    if not meta.get("name") or not meta.get("description"):
        return None
    return {"meta": meta, "body": match.group(2).strip()}


def _serialize_skill(skill: Skill) -> str:
    return (
        f"---\nname: {skill.name}\ndescription: {skill.description}\n---\n\n"
        f"{skill.body.strip()}\n"
    )


class SkillStore:
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.root = self.config.base_path / "skills"
        self.proposals_root = self.root / PROPOSALS_DIR
        self.proposals_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ read

    def _load_dir(self, root: Path) -> List[Skill]:
        skills = []
        if not root.exists():
            return skills
        for entry in sorted(root.iterdir()):
            if not entry.is_dir() or entry.name == PROPOSALS_DIR:
                continue
            md = entry / "SKILL.md"
            if not md.is_file():
                continue
            parsed = _parse_skill_md(md.read_text(encoding="utf-8"))
            if parsed is None:
                continue
            skills.append(
                Skill(
                    name=parsed["meta"]["name"],
                    description=parsed["meta"]["description"],
                    body=parsed["body"],
                    path=str(md),
                )
            )
        return skills

    def list_active(self) -> List[Skill]:
        return self._load_dir(self.root)

    def list_proposals(self) -> List[Skill]:
        return self._load_dir(self.proposals_root)

    def get(self, name: str) -> Optional[Skill]:
        for skill in self.list_active():
            if skill.name == name:
                return skill
        return None

    def prompt_block(self) -> str:
        skills = self.list_active()
        if not skills:
            return ""
        lines = ["", "Available skills (fetch instructions with the skill_use tool):"]
        lines += [f"- {s.name}: {s.description}" for s in skills]
        return "\n".join(lines)

    # ----------------------------------------------------------------- write

    def _check_name(self, name: str) -> None:
        if not _NAME_RE.match(name):
            raise ValueError(
                f"Invalid skill name {name!r} (lowercase letters, digits, hyphens)"
            )

    def propose(self, name: str, description: str, body: str,
                evidence: Optional[dict] = None) -> Skill:
        self._check_name(name)
        skill = Skill(name=name, description=description, body=body)
        target = self.proposals_root / name
        target.mkdir(parents=True, exist_ok=True)
        md = target / "SKILL.md"
        md.write_text(_serialize_skill(skill), encoding="utf-8")
        if evidence is not None:
            (target / "evidence.json").write_text(
                json.dumps(evidence, indent=2), encoding="utf-8"
            )
        skill.path = str(md)
        return skill

    def evidence(self, name: str) -> Optional[dict]:
        """Validation evidence for a forged skill (from proposal or active dir)."""
        for root in (self.proposals_root / name, self.root / name):
            path = root / "evidence.json"
            if path.is_file():
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    return None
        return None

    def approve(self, name: str, overwrite: bool = False) -> Skill:
        self._check_name(name)
        source = self.proposals_root / name
        if not (source / "SKILL.md").is_file():
            raise KeyError(f"No proposal named {name!r}")
        target = self.root / name
        if target.exists():
            if not overwrite:
                raise FileExistsError(f"Active skill {name!r} already exists")
            shutil.rmtree(target)
        shutil.move(str(source), str(target))
        skill = self.get(name)
        assert skill is not None
        return skill

    def reject(self, name: str) -> None:
        self._check_name(name)
        source = self.proposals_root / name
        if not source.exists():
            raise KeyError(f"No proposal named {name!r}")
        shutil.rmtree(source)
