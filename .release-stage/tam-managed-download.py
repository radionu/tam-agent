#!/usr/bin/env python3
"""Pinned root bootstrap downloader. Fetch only; no enrollment, service or trust changes."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import stat
import tempfile
import time
import urllib.parse

HOSTS = {'github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com'}
ROLES = {'admin': 'tam-edge-admin', 'supervisor': 'tam-edge-supervisor', 'supervisor-unit': 'tam-edge-supervisor@.service', 'runtime-unit': 'tam-edge-runtime@.service'}
BASE = Path('/var/lib/tam-edge/bootstrap-downloads')

def url(raw, initial=False):
    u = urllib.parse.urlsplit(raw)
    if u.scheme != 'https' or u.netloc not in HOSTS or u.username or u.fragment or '\\' in raw or any(ord(c) < 33 for c in raw):
        raise ValueError('download origin refused')
    if initial and (u.netloc != 'github.com' or u.query or not re.fullmatch(r'/[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+/releases/download/[A-Za-z0-9._-]+/[A-Za-z0-9@._-]+', u.path)):
        raise ValueError('initial URL refused')
    return u

def fetch(raw, size, digest):
    url(raw, True)
    deadline = time.monotonic() + 600
    for redirects in range(6):
        u = url(raw)
        conn = http.client.HTTPSConnection(u.netloc, timeout=30, context=ssl.create_default_context())
        try:
            conn.request('GET', urllib.parse.urlunsplit(('', '', u.path, u.query, '')), headers={'Accept-Encoding': 'identity'})
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                raw = urllib.parse.urljoin(raw, r.getheader('Location', ''))
                url(raw)
                continue
            if r.status != 200 or r.getheader('Content-Encoding', 'identity') != 'identity':
                raise ValueError('download response refused')
            length = r.getheader('Content-Length')
            if length is not None and (not length.isdecimal() or int(length) > size):
                raise ValueError('download bound exceeded')
            chunks = []
            count = 0
            while count <= size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('download deadline')
                if getattr(conn, 'sock', None) is not None:
                    conn.sock.settimeout(min(30, remaining))
                chunk = r.read1(min(65536, size + 1 - count))
                if not chunk:
                    break
                chunks.append(chunk)
                count += len(chunk)
            data = b''.join(chunks)
            if len(data) > size or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('download pin mismatch or incomplete file')
            return data
        finally:
            conn.close()
    raise ValueError('redirect limit')

def unique(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError('duplicate descriptor key')
        d[k] = v
    return d

def descriptor(raw):
    d = json.loads(raw, object_pairs_hook=unique)
    if set(d) != {'format', 'source_commit', 'platform', 'repository', 'files'} or d['format'] != 'tam-edge-bootstrap/1' or not re.fullmatch('[0-9a-f]{40}', d['source_commit']) or not re.fullmatch('[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', d['repository']):
        raise ValueError('descriptor identity refused')
    arch = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(os.uname().machine)
    if d['platform'] != 'linux-' + str(arch) or not isinstance(d['files'], list) or len(d['files']) != 4:
        raise ValueError('platform/files refused')
    seen = set()
    for f in d['files']:
        if set(f) != {'role', 'name', 'size', 'sha256', 'source'} or f['role'] in seen or ROLES.get(f['role']) != f['name'] or type(f['size']) is not int or not 0 < f['size'] <= 256 * 1024**2 or not re.fullmatch('[0-9a-f]{64}', f['sha256']):
            raise ValueError('descriptor file refused')
        seen.add(f['role'])
        u = url(f['source'], True)
        if not u.path.startswith('/' + d['repository'] + '/releases/download/') or u.path.rsplit('/', 1)[1] != f['name']:
            raise ValueError('mixed source refused')
    if sum(f['size'] for f in d['files']) > 512 * 1024**2:
        raise ValueError('bundle too large')
    return d

def secure_base():
    for part in [Path('/var'), Path('/var/lib'), Path('/var/lib/tam-edge'), BASE]:
        if not part.exists():
            part.mkdir(mode=0o700)
        st = part.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            raise ValueError('unsafe root staging ancestor')

def acquire(raw, base, runtime_base=None, manifest_pin=None, signature_pin=None):
    """Fetch pinned bytes into an exact stageable layout; stage verifies typed trust."""
    d = descriptor(raw)
    stage = Path(tempfile.mkdtemp(prefix='incoming-', dir=base))
    stage.chmod(0o700)
    try:
        assets = stage / 'assets'
        assets.mkdir(mode=0o700)
        (stage / 'bootstrap-descriptor.json').write_bytes(raw)
        for f in d['files']:
            data = fetch(f['source'], f['size'], f['sha256'])
            if len(data) != f['size']:
                raise ValueError('file size mismatch')
            (assets / f['name']).write_bytes(data)
        if runtime_base is not None:
            # The reviewed package conveys these exact immutable release pins.
            # No manifest-controlled URLs or arbitrary output names are accepted.
            url(runtime_base + '/tam-edge-runtime.manifest.json', True)
            for pin in [manifest_pin, signature_pin]:
                if type(pin) is not str or not re.fullmatch('[0-9a-f]{64}', pin):
                    raise ValueError('runtime independent pins required')
            manifest = fetch(runtime_base + '/tam-edge-runtime.manifest.json', 16384, manifest_pin)
            signature = fetch(runtime_base + '/tam-edge-runtime.manifest.json.jws', 1024, signature_pin)
            m = json.loads(manifest, object_pairs_hook=unique)
            arch = d['platform'].removeprefix('linux-')
            name = 'tam-edge-linux-' + arch
            # This is a bounded acquisition selector, not a signature validator.
            # Actual stage reuses the typed manifest/JWS/ELF validators before mutation.
            if type(m) is not dict or type(m.get('artifacts')) is not list or len(m['artifacts']) > 2:
                raise ValueError('runtime acquisition inventory refused')
            selected = [x for x in m['artifacts'] if type(x) is dict and x.get('os') == 'linux' and x.get('arch') == arch]
            if len(selected) != 1:
                raise ValueError('runtime native artifact missing or duplicate')
            f = selected[0]
            if (set(f) != {'os', 'arch', 'name', 'size', 'sha256'} or f['name'] != name
                or type(f['size']) is not int or not 0 < f['size'] <= 256 * 1024**2
                or type(f['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', f['sha256'])):
                raise ValueError('runtime acquisition pin refused')
            data = fetch(runtime_base + '/' + name, f['size'], f['sha256'])
            if len(data) != f['size']:
                raise ValueError('runtime size differs')
            runtime = stage / 'runtime'
            runtime.mkdir(mode=0o700)
            for n, b in [('tam-edge-runtime.manifest.json', manifest), ('tam-edge-runtime.manifest.json.jws', signature), (name, data)]:
                (runtime / n).write_bytes(b)
        for f in stage.rglob('*'):
            if f.is_file():
                f.chmod(0o600)
        # Descriptor pin was verified by the caller before acquisition. All bootstrap
        # files are hash verified before granting execute permission to this admin.
        (assets / 'tam-edge-admin').chmod(0o700)
        return stage
    except BaseException:
        shutil.rmtree(stage)
        raise

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--descriptor-url', required=True)
    p.add_argument('--descriptor-sha256', required=True)
    p.add_argument('--runtime-base-url', help='reviewed immutable GitHub release URL, no trailing slash')
    p.add_argument('--manifest-sha256')
    p.add_argument('--signature-sha256')
    a = p.parse_args()
    if os.getuid() != 0 or os.geteuid() != 0:
        raise ValueError('root required')
    if not re.fullmatch('[0-9a-f]{64}', a.descriptor_sha256):
        raise ValueError('independently conveyed SHA256 required')
    if any([a.runtime_base_url, a.manifest_sha256, a.signature_sha256]) and not all([a.runtime_base_url, a.manifest_sha256, a.signature_sha256]):
        raise ValueError('all runtime acquisition inputs required together')
    raw = fetch(a.descriptor_url, 65536, a.descriptor_sha256)
    descriptor(raw)
    if a.runtime_base_url:
        u = url(a.runtime_base_url + '/tam-edge-runtime.manifest.json', True)
        if not u.path.startswith('/' + descriptor(raw)['repository'] + '/releases/download/'):
            raise ValueError('runtime repository differs')
    secure_base()
    stage = acquire(raw, BASE, a.runtime_base_url, a.manifest_sha256, a.signature_sha256)
    print('Pinned download directory:', stage)
    print('Bootstrap descriptor:', stage / 'bootstrap-descriptor.json')
    print('Exact four-file bundle:', stage / 'assets')
    print('No service, identity or trust was changed. Stage must verify publisher signature and typed runtime inputs.')

if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never print redirect URLs, query strings, HTTP exception details or credentials.
        raise SystemExit('managed download refused; no installation performed')
