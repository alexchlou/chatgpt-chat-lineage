#!/usr/bin/env python3
"""Build and verify a source ZIP from a clean tracked tree with an exact manifest."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import zipfile
import check_release


def sha(raw): return hashlib.sha256(raw).hexdigest()


def verify(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.comment or archive.testzip():
            raise ValueError('Duplicate entries, archive comment, or CRC failure')
        for entry in archive.infolist():
            p = PurePosixPath(entry.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in entry.filename or entry.comment or (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unsafe ZIP entry')
        manifest = json.loads(archive.read('SOURCE_MANIFEST.json'))
        records = manifest['files']
        if len(records) != len({r['path'] for r in records}) or set(names) != {r['path'] for r in records} | {'SOURCE_MANIFEST.json'}:
            raise ValueError('Incomplete source manifest')
        for record in records:
            raw = archive.read(record['path'])
            if sha(raw) != record['sha256']: raise ValueError('Source hash mismatch')
            if record['path'] != 'assets/demo-preview.png':
                if check_release.scan_text(raw.decode('utf-8'), record['path']):
                    raise ValueError('Privacy check failed inside ZIP')
    return {'verified':True,'files':len(records),'sha256':sha(Path(path).read_bytes()),'commit':manifest['commit']}


def build(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    def git(*args):
        return subprocess.check_output(['git','-C',str(root),*args])
    if git('status','--porcelain','--untracked-files=normal').strip():
        raise ValueError('Release requires a clean tracked source tree')
    result = check_release.check(root)
    if result['status'] != 'PASS': raise ValueError('Source privacy check failed')
    files = [p for p in git('ls-files','-z').decode().split('\0') if p]
    allowed = {p.relative_to(root).as_posix() for p in check_release.source_files(root)}
    if set(files) != allowed: raise ValueError('Tracked tree does not match release inventory')
    content = {name:(root/name).read_bytes() for name in files}
    commit = git('rev-parse','HEAD').decode().strip()
    # Verify that the source bytes come from HEAD, not a working-tree transformation.
    for name, raw in content.items():
        if git('show','HEAD:'+name) != raw: raise ValueError('Working bytes differ from HEAD')
    manifest = {'schema_version':'1.0.0','commit':commit,'files':[{'path':name,'sha256':sha(raw)} for name,raw in sorted(content.items())]}
    content['SOURCE_MANIFEST.json'] = (json.dumps(manifest,indent=2)+'\n').encode()
    destination.parent.mkdir(parents=True,exist_ok=True)
    with destination.open('xb') as stream:
        with zipfile.ZipFile(stream,'w') as archive:
            for name, raw in sorted(content.items()):
                entry=zipfile.ZipInfo(name,(2020,1,1,0,0,0));entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o100644<<16
                archive.writestr(entry,raw)
    return verify(destination)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output');parser.add_argument('--verify')
    args = parser.parse_args()
    if not args.output and not args.verify: parser.error('--output or --verify required')
    print(json.dumps(verify(args.verify) if args.verify else build(Path(__file__).resolve().parents[1],args.output),indent=2))
