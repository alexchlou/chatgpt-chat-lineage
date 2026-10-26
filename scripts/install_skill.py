#!/usr/bin/env python3
"""Install only the reusable skill files into a new directory; never overwrite."""
import argparse
import json
from pathlib import Path
import shutil

FILES = ('SKILL.md', 'PROMPT.md', 'manifest.json', 'research_config.example.json', 'LICENSE')
FOLDERS = ('agents', 'references', 'scripts', 'assets')


def install(source, destination):
    source, destination = Path(source).resolve(), Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('Destination exists; choose a new directory, do not overwrite a live skill')
    if destination == source or source in destination.parents:
        raise ValueError('Install outside the source checkout')
    candidates = [source / name for name in FILES]
    candidates += [p for name in FOLDERS for p in (source / name).rglob('*')
                   if '__pycache__' not in p.parts and p.name != '.DS_Store' and p.suffix not in {'.pyc', '.pyo'} and not p.is_dir()]
    if any(p.is_symlink() or not p.is_file() for p in candidates):
        raise ValueError('Source files must be regular files, not symlinks')
    # Validate the complete tree before copying any file.
    for name in FOLDERS:
        if (source / name).is_symlink() or any(p.is_symlink() for p in (source / name).rglob('*')):
            raise ValueError('Source folders must not contain symlinks')
    destination.mkdir(parents=True, exist_ok=False)
    for path in candidates:
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    return {'installed': True, 'files': len(candidates), 'persistence_enabled': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', default=str(Path.home()/'.codex/skills/chatgpt-conversation-rename'))
    args = parser.parse_args()
    print(json.dumps(install(Path(__file__).resolve().parents[1], args.destination)))
