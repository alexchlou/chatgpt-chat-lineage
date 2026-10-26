#!/usr/bin/env python3
"""Initialize an explicitly chosen private metadata dataset; no browser or mail."""
import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo
import research_journal as journal


def configure(skill_root, dataset, timezone='UTC'):
    skill_root, dataset = Path(skill_root).resolve(), Path(dataset).expanduser().resolve()
    ZoneInfo(timezone)
    config = skill_root / 'research_config.json'
    if config.exists():
        raise ValueError('Local configuration exists; reconcile it without overwriting')
    if dataset == skill_root or skill_root in dataset.parents:
        raise ValueError('Keep the private dataset outside the installed skill/repository')
    if dataset.exists() and (not dataset.is_dir() or any(dataset.iterdir())):
        raise ValueError('Choose a new or empty dedicated dataset')
    template = json.loads((skill_root / 'research_config.example.json').read_text())
    template.update(enabled=True, dataset_root=str(dataset), timezone=timezone)
    template['knowledge_graph']['enabled'] = True
    journal.init(dataset)
    out = dataset / 'knowledge_graph'; out.mkdir()
    journal.atomic_write(out / 'config.json', json.dumps({'enabled': True, 'obsidian': {'enabled': False}}, indent=2) + '\n')
    journal.atomic_write(out / 'relationship_registry.json', json.dumps({'schema_version':'1.0.0','assertions':[], 'domains':[], 'conversation_annotations':[]}) + '\n')
    # Exclusive creation prevents replacing another configuration during setup.
    with config.open('x', encoding='utf-8') as stream:
        json.dump(template, stream, indent=2); stream.write('\n')
    config.chmod(0o600)
    return {'configured': True, 'persistence': True, 'graph': True, 'email': False, 'obsidian': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--timezone', default='UTC')
    args = parser.parse_args()
    print(json.dumps(configure(Path(__file__).resolve().parents[1], args.dataset, args.timezone)))
