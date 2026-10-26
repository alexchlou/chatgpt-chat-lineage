#!/usr/bin/env python3
"""Check public source bytes, not private runtime data. Not a complete DLP system."""
import argparse
import json
from pathlib import Path
import re
import sys
import unicodedata

ROOT_FILES = {'README.md','LICENSE','SECURITY.md','CONTRIBUTING.md','CHANGELOG.md','SKILL.md','PROMPT.md',
              'manifest.json','research_config.example.json','package.json','package-lock.json','.gitignore','.gitattributes'}
FOLDERS = {'scripts','tests','references','assets','agents','docs','examples','.github'}
OMIT = {'.git','node_modules','build','dist','.venv','venv','__pycache__'}
TEXT_SUFFIXES = {'.md','.py','.js','.cjs','.json','.jsonl','.yaml','.yml','.html','.csv','.txt','.toml','.svg','.graphml'}
EMAIL = re.compile(r'[\w.+%-]+@[\w.-]+\.[A-Za-z]{2,}', re.UNICODE)
HOME_PATH = re.compile(r'(?:/Users/|/home/)[A-Za-z0-9_.-]+|[A-Za-z]:\\Users\\[^\\\s]+')
CHAT_ID = re.compile(r'https?://(?:chatgpt\.com|chat\.openai\.com)/(?:g/[^/\s]+/)?c/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', re.I)
SECRETS = re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|AIza[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|Bearer\s+[A-Za-z0-9._-]{24,})')


def scan_text(text, name='input.txt'):
    # Normalize JSON escapes and percent escapes as well as the direct text.
    from urllib.parse import unquote
    variants = [text, unquote(text)]
    variants += [re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1],16)), text)]
    findings = set()
    for candidate in variants:
        candidate = unicodedata.normalize('NFKC', candidate)
        if HOME_PATH.search(candidate): findings.add('private_home_path')
        if CHAT_ID.search(candidate): findings.add('real_looking_chat_id')
        if SECRETS.search(candidate): findings.add('secret_pattern')
        for match in EMAIL.finditer(candidate):
            domain = match.group().rsplit('@',1)[1].lower()
            if domain not in {'example.com','example.org','example.net'} and not domain.endswith(('.test','.invalid')):
                findings.add('non_example_email')
    if name != 'scripts/cua_workflow.js' and re.search('[\u3400-\u9fff]', text):
        findings.add('non_english_prose')
    return sorted(findings)


def source_files(root):
    root = Path(root).resolve()
    files = []
    for p in sorted(root.rglob('*')):
        relative = p.relative_to(root)
        if any(part in OMIT for part in relative.parts) or p.name == '.DS_Store':
            continue
        if p.is_symlink():
            raise ValueError('Symlink is not publishable: ' + str(relative))
        if p.is_dir():
            continue
        if relative.parts[0] not in FOLDERS and str(relative) not in ROOT_FILES:
            raise ValueError('Unexpected release path: ' + str(relative))
        if p.suffix in {'.pyc','.pyo'}: continue
        files.append(p)
    return files


def check(root):
    root = Path(root).resolve(); findings = []; files = source_files(root)
    for p in files:
        name = p.relative_to(root).as_posix()
        if p.suffix == '.png' and name == 'assets/demo-preview.png':
            if not p.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
                findings.append({'path':name,'rules':['invalid_preview_png']})
            continue
        if p.suffix not in TEXT_SUFFIXES and p.name not in ROOT_FILES:
            findings.append({'path':name,'rules':['unexpected_file_type']}); continue
        try:
            rules = scan_text(p.read_text(encoding='utf-8'), name)
        except UnicodeDecodeError:
            rules = ['unexpected_binary']
        if rules: findings.append({'path': name, 'rules':rules})
    config = json.loads((root/'research_config.example.json').read_text())
    if config.get('enabled') is not False or config.get('dataset_root') is not None or config.get('email_archive',{}).get('enabled') is not False:
        findings.append({'path':'research_config.example.json','rules':['unsafe_default_config']})
    return {'status':'PASS' if not findings else 'FAIL','files_checked':len(files),'findings':findings,
            'limits':'Pattern-based source check; use an independent secret scanner and review actual data provenance.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    try:
        result = check(args.root)
    except (ValueError, OSError) as error:
        result = {'status':'FAIL','reason':str(error)}
    print(json.dumps(result,indent=2)); sys.exit(0 if result['status']=='PASS' else 1)
