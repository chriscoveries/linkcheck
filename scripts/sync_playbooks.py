"""Copy canonical playbooks and result schemas into package data."""

from pathlib import Path
import shutil


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = root / "src" / "linkcheck" / "playbooks"
    target.mkdir(exist_ok=True)
    for source in sorted((root / "playbooks").iterdir()):
        if source.is_file() and source.suffix in {".md", ".json"}:
            shutil.copyfile(source, target / source.name)
    docs = root / "src" / "linkcheck" / "docs"
    docs.mkdir(exist_ok=True)
    for name in ("schema.md", "dataset.md"):
        shutil.copyfile(root / "docs" / name, docs / name)


if __name__ == "__main__":
    main()
