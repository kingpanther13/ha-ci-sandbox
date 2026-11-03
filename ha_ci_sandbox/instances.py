"""Resolve application bundles and persistent data profiles before namespaces start."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile
import urllib.parse
import urllib.request


def resolve(options):
    count = options.get('instances', 1)
    if type(count) is not int or not 1 <= count <= 8:
        raise ValueError('instances must be an integer from 1 to 8')
    overrides = {}
    for row in options.get('instance_profiles', []):
        number = row.get('instance')
        if type(number) is not int or not 1 <= number <= count or number in overrides:
            raise ValueError('Each instance profile must name a unique enabled instance')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', row.get('profile', '')):
            raise ValueError('profile must contain 1..64 letters, digits, underscores or hyphens')
        overrides[number] = row
    plans = []
    for number in range(1, count + 1):
        row = overrides.get(number, {})
        profile = row.get('profile', '')
        custom_source = bool(row.get('bundle_dir') or row.get('bundle_url'))
        source = row if custom_source else options
        directory = source.get('bundle_dir') or ('' if custom_source else '/share/ha-ci-sandbox')
        url = source.get('bundle_url') or ''
        checksum = (row.get('bundle_sha256') or source.get('bundle_sha256') or '').lower()
        if directory and (not directory.startswith('/share/') or '..' in PurePosixPath(directory).parts):
            raise ValueError('bundle_dir must be a directory below /share')
        if url and urllib.parse.urlsplit(url).scheme not in ('http', 'https'):
            raise ValueError('bundle_url must use HTTP or HTTPS')
        if checksum and not re.fullmatch(r'[0-9a-f]{64}', checksum):
            raise ValueError('bundle_sha256 must be a SHA-256 hex digest')
        suffix = '' if number == 1 else f'-{number}'
        data = f'/data/hub{suffix}'
        work = f'/data/work{suffix}'
        cache = '/data/bundle'
        if profile:
            root = f'/data/profiles/{profile}/instance-{number}'
            data, work = root + '/hub', root + '/work'
            key = hashlib.sha256(json.dumps([directory, url, checksum]).encode()).hexdigest()[:24]
            cache = f'/data/bundles/{profile}/{key}'
        plans.append(dict(instance=number, profile=profile, data_dir=data, work_dir=work,
                          bundle_dir=directory, bundle_url=url, bundle_sha256=checksum,
                          cache_dir=cache))
    return plans


def has_bundle(path):
    return bool(path) and (Path(path) / 'app.jar').is_file() and (Path(path) / 'launcher/start.sh').is_file()


def extract_bundle(archive_path, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.bundle-', dir=destination.parent) as tmp:
        staging = Path(tmp)
        with tarfile.open(archive_path, 'r:gz') as archive:
            members = archive.getmembers()
            for member in members:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or '..' in path.parts or '\\' in member.name
                        or not (member.isfile() or member.isdir())):
                    raise ValueError('Bundle archive contains an unsafe path or non-regular entry')
            archive.extractall(staging, members=members, filter='data')
        source = staging
        if not has_bundle(source):
            children = list(staging.iterdir())
            if len(children) != 1 or not children[0].is_dir() or not has_bundle(children[0]):
                raise ValueError('Bundle needs app.jar and launcher/start.sh')
            source = children[0]
        # Publish only a complete bundle; never touch a database or a working copy.
        if destination.is_symlink() or has_bundle(destination):
            raise ValueError('Refusing to replace a complete bundle or symlink')
        with tempfile.TemporaryDirectory(prefix='.previous-', dir=destination.parent) as previous:
            backup = Path(previous) / 'bundle'
            if destination.exists():
                destination.rename(backup)
            try:
                source.rename(destination)
            except OSError:
                if backup.exists():
                    backup.rename(destination)
                raise


def prepare_bundle(plan):
    if has_bundle(plan['bundle_dir']) or has_bundle(plan['cache_dir']) or not plan['bundle_url']:
        return
    target = Path(plan['cache_dir'])
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.download-', dir=target.parent) as tmp:
        archive = Path(tmp) / 'bundle.tar.gz'
        digest = hashlib.sha256()
        with urllib.request.urlopen(plan['bundle_url'], timeout=60) as response, archive.open('wb') as output:
            while chunk := response.read(1024 * 1024):
                digest.update(chunk)
                output.write(chunk)
        if plan['bundle_sha256'] and digest.hexdigest() != plan['bundle_sha256']:
            raise ValueError('Bundle checksum mismatch')
        extract_bundle(archive, target)


def prepare_instances(plans, output):
    for plan in plans:
        try:
            prepare_bundle(plan)
        except Exception as error:
            # Signed URLs may appear in exception messages; keep them out of logs.
            print(f"Instance {plan['instance']} bundle preparation failed ({type(error).__name__}); waiting for its bundle.", flush=True)
        for key in ('data_dir', 'work_dir'):
            Path(plan[key]).mkdir(parents=True, exist_ok=True)
    # The shell's debug tracing and application namespaces need paths, not signed URLs.
    runtime_plans = [{key: value for key, value in plan.items()
                      if key not in ('bundle_url', 'bundle_sha256')} for plan in plans]
    output.write_text(json.dumps(runtime_plans))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--options', type=Path, default=Path('/data/options.json'))
    parser.add_argument('--output', type=Path, default=Path('/run/sb/instances.json'))
    args = parser.parse_args()
    prepare_instances(resolve(json.loads(args.options.read_text())), args.output)


if __name__ == '__main__':
    main()
