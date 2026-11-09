"""Package the exact upstream Qt/PySide sources beside the Windows release."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import urllib.request
import zipfile


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=root / 'dist')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(root) or output == root:
        parser.error('Release output must be a subdirectory of the source workspace.')
    docs = root / 'vendor' / 'redistribution'
    manifest = json.loads((docs / 'qt-pyside-manifest.json').read_text(encoding='utf-8'))
    cache = root / 'build' / 'qt-sources-cache'
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    sources = []
    for entry in manifest['sources']:
        name = entry['filename']
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('Unexpected source archive filename.')
        target = cache / name
        if not target.exists() or digest(target) != entry['sha256']:
            partial = target.with_suffix(target.suffix + '.partial')
            with urllib.request.urlopen(entry['url'], timeout=60) as response, partial.open('wb') as stream:
                while block := response.read(1024 * 1024):
                    stream.write(block)
            if digest(partial) != entry['sha256']:
                raise ValueError(f'Upstream source checksum mismatch: {name}')
            os.replace(partial, target)
        sources.append(target)
    destination = output / manifest['source_bundle']
    temporary = destination.with_suffix('.tmp')
    prefix = f"KeepQuiet-Qt-PySide-{manifest['version']}-source"
    with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
        for source in sources:
            # Upstream xz files are already compressed; preserve their bytes.
            archive.write(source, f'{prefix}/sources/{source.name}', compress_type=zipfile.ZIP_STORED)
        for source in sorted(docs.iterdir()):
            if source.is_file():
                archive.write(source, f'{prefix}/vendor/redistribution/{source.name}')
        for component in ('Qt', 'QtForPython', 'PySide6-Essentials', 'shiboken6', 'KeepQuiet'):
            for source in sorted((root / 'vendor' / 'licenses' / component).rglob('*')):
                if source.is_file():
                    relative = source.relative_to(root / 'vendor' / 'licenses')
                    archive.write(source, f'{prefix}/vendor/licenses/{relative.as_posix()}')
        checksums = ''.join(f"{entry['sha256']}  sources/{entry['filename']}\n" for entry in manifest['sources'])
        archive.writestr(f'{prefix}/SOURCE_SHA256SUMS.txt', checksums)
        archive.writestr(f'{prefix}/README.md',
            '# Qt / PySide corresponding sources\n\n'
            'The sources/ directory contains the original, unmodified Qt Base and Qt for Python source archives. '
            'Verify them with SOURCE_SHA256SUMS.txt.\n\n'
            'Read vendor/redistribution/QT_PYSIDE_NOTICE.html for the offline license notice, '
            'vendor/redistribution/REBUILD_AND_REPLACE.md for rebuilding and library replacement, and '
            'vendor/redistribution/qt-pyside-manifest.json for exact provenance. '
            'Original licenses and attributions are retained under vendor/licenses/.\n\n'
            'Publish this archive at the same Release download location as the corresponding KeepQuiet Windows binary.\n')
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise ValueError('Corresponding-source archive integrity check failed.')
    os.replace(temporary, destination)
    print(f'Corresponding Qt/PySide sources ready: {destination}')


if __name__ == '__main__':
    main()
