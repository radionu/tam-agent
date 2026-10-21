#!/usr/bin/env python3
"""Staged GitHub release publication for public TAM delivery assets.

stage    Worker, offline: commit exact pinned assets and a request file into a
         clean clone of the public repository as one new staging branch, then
         print the push command. Pushes, publishes and stores nothing remotely.
publish  GitHub Actions (push of release-stage/<kind>/<tag>): validate the
         staged request and publish it with the workflow token. Never deletes,
         replaces or overwrites a release asset or ref; an identical repeat is a
         no-op and a draft this request did not create is never touched.
verify   Anyone, unauthenticated: compare a published release with exact pins.

Standard library only (plus the openssl CLI for Ed25519 JWS checks). The
token is read from GITHUB_TOKEN and is never printed or passed to Git.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

FORMAT = 'tam-release-stage/1'
STAGE = '.release-stage'
REQUEST = 'request.json'
MANIFEST = 'tam-edge-runtime.manifest.json'
JWS = MANIFEST + '.jws'
RUNTIME = [MANIFEST, 'tam-edge-linux-amd64', 'tam-edge-linux-arm64']
BOOTSTRAP = ['bootstrap-descriptor.json', 'tam-edge-admin', 'tam-edge-supervisor',
             'tam-edge-supervisor@.service', 'tam-edge-runtime@.service', 'tam-managed-download.py']
ROLES = {'admin': 'tam-edge-admin', 'supervisor': 'tam-edge-supervisor',
         'supervisor-unit': 'tam-edge-supervisor@.service', 'runtime-unit': 'tam-edge-runtime@.service'}
MANAGED_TAG = re.compile(r'managed-(0\.[0-9]+\.[0-9]+-[A-Za-z0-9.-]+)-([0-9a-f]{7})')
BOOTSTRAP_TAG = re.compile(r'bootstrap-([0-9a-f]{40})-(amd64|arm64)')
REPOSITORY = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})/[A-Za-z0-9._-]{1,100}')
CREATE_KINDS = ('runtime-candidate', 'bootstrap')
ATTACH_KINDS = ('runtime-signature', 'downloads-archive')
MAX_ASSET = 256 * 1024**2
ED25519_SPKI = bytes.fromhex('302a300506032b6570032100')
BODY = {
    'runtime-candidate': 'Unsigned TAM edge runtime candidate {tag}. Not installable on its own: TAM Center verifies and '
                         'signs this exact manifest; the detached signature is attached to this release afterwards.',
    'bootstrap': 'TAM edge bootstrap bundle {tag}. Verify bootstrap-descriptor.json against the SHA-256 conveyed through '
                 'the independent operator pin channel before use.',
}


class Refused(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(raw):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise Refused('duplicate JSON key')
            result[k] = v
        return result
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=unique)
    except (UnicodeDecodeError, ValueError) as error:
        raise Refused('invalid JSON: ' + str(error)) from None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def read_regular(path):
    path = Path(path)
    for p in [path, *path.parents]:
        if p.is_symlink():
            raise Refused('symlink input refused: ' + str(path))
    st = path.stat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or not 0 < st.st_size <= MAX_ASSET:
        raise Refused('nonregular, linked, empty or oversized input: ' + str(path))
    return path.read_bytes()


def b64e(data):
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def b64d(text):
    if not re.fullmatch('[A-Za-z0-9_-]*', text):
        raise Refused('invalid base64url')
    data = base64.urlsafe_b64decode(text + '=' * (-len(text) % 4))
    if b64e(data) != text:
        raise Refused('non-canonical base64url')
    return data


def rules(kind, tag):
    """New and pre-existing asset names allowed for one kind and tag."""
    if kind in ('runtime-candidate',) + ATTACH_KINDS and not MANAGED_TAG.fullmatch(tag):
        raise Refused('runtime tag must be managed-<version>-<commit7>')
    if kind == 'runtime-candidate':
        return set(RUNTIME), set()
    if kind == 'runtime-signature':
        return {JWS}, set(RUNTIME)
    if kind == 'downloads-archive':
        return {'tam-downloads-' + tag + '.tar.gz'}, set(RUNTIME) | {JWS}
    if kind == 'bootstrap':
        if not BOOTSTRAP_TAG.fullmatch(tag):
            raise Refused('bootstrap tag must be bootstrap-<commit>-<arch>')
        return set(BOOTSTRAP), set()
    raise Refused('unknown kind')


def check_pins(pins):
    if type(pins) is not dict:
        raise Refused('pin map refused')
    for name, pin in pins.items():
        if (type(pin) is not dict or set(pin) != {'size', 'sha256'}
                or type(pin['size']) is not int or not 0 < pin['size'] <= MAX_ASSET
                or type(pin['sha256']) is not str or not re.fullmatch('[0-9a-f]{64}', pin['sha256'])):
            raise Refused('pin schema refused: ' + name)


def load_request(raw):
    r = strict_json(raw)
    if type(r) is not dict or set(r) != {'format', 'kind', 'repository', 'tag', 'assets', 'existing'}:
        raise Refused('request schema refused')
    if r['format'] != FORMAT or type(r['kind']) is not str or type(r['tag']) is not str:
        raise Refused('request format refused')
    if type(r['repository']) is not str or not REPOSITORY.fullmatch(r['repository']):
        raise Refused('repository refused')
    new, existing = rules(r['kind'], r['tag'])
    check_pins(r['assets'])
    check_pins(r['existing'])
    if set(r['assets']) != new or set(r['existing']) != existing:
        raise Refused('request asset allowlist differs for ' + r['kind'])
    return r


def check_bytes(pins, files, what):
    if set(files) != set(pins):
        raise Refused(what + ' inventory differs from pins')
    for name, data in files.items():
        if len(data) != pins[name]['size'] or sha(data) != pins[name]['sha256']:
            raise Refused(what + ' bytes differ from pin: ' + name)


def check_manifest(tag, data, pins):
    version, commit7 = MANAGED_TAG.fullmatch(tag).groups()
    m = strict_json(data)
    if type(m) is not dict or canonical(m) != data:
        raise Refused('manifest is not canonical JSON')
    if (m.get('format') != 1 or m.get('product') != 'tam-edge-runtime' or m.get('version') != version
            or type(m.get('source_commit')) is not str or not re.fullmatch('[0-9a-f]{40}', m['source_commit'])
            or not m['source_commit'].startswith(commit7)):
        raise Refused('manifest identity differs from tag')
    artifacts = m.get('artifacts')
    if type(artifacts) is not list or len(artifacts) != 2 or any(type(a) is not dict for a in artifacts):
        raise Refused('manifest artifacts refused')
    if {(a.get('os'), a.get('arch'), a.get('name')) for a in artifacts} != {
            ('linux', arch, 'tam-edge-linux-' + arch) for arch in ('amd64', 'arm64')}:
        raise Refused('manifest platform set differs')
    for a in artifacts:
        pin = pins[a['name']]
        if a.get('size') != pin['size'] or a.get('sha256') != pin['sha256']:
            raise Refused('manifest artifact pin differs: ' + a['name'])


def check_bootstrap(tag, repository, files):
    commit, arch = BOOTSTRAP_TAG.fullmatch(tag).groups()
    raw = files['bootstrap-descriptor.json']
    d = strict_json(raw)
    if type(d) is not dict or canonical(d) != raw:
        raise Refused('bootstrap descriptor is not canonical JSON')
    if (set(d) != {'format', 'source_commit', 'platform', 'repository', 'files'} or d['format'] != 'tam-edge-bootstrap/1'
            or d['source_commit'] != commit or d['platform'] != 'linux-' + arch or d['repository'] != repository):
        raise Refused('bootstrap descriptor identity differs from tag/repository')
    if type(d['files']) is not list or len(d['files']) != len(ROLES):
        raise Refused('bootstrap descriptor file list refused')
    seen = {}
    for f in d['files']:
        if type(f) is not dict or set(f) != {'role', 'name', 'size', 'sha256', 'source'} or f['role'] in seen:
            raise Refused('bootstrap descriptor entry refused')
        seen[f['role']] = f
        if ROLES.get(f['role']) != f['name']:
            raise Refused('bootstrap role/name differs')
        data = files[f['name']]
        if f['size'] != len(data) or f['sha256'] != sha(data):
            raise Refused('bootstrap file differs from descriptor: ' + f['name'])
        if f['source'] != f'https://github.com/{repository}/releases/download/{tag}/{f["name"]}':
            raise Refused('bootstrap source URL differs: ' + f['name'])
    if not files['tam-managed-download.py'].startswith(b'#!/usr/bin/env python3\n'):
        raise Refused('downloader is not the expected Python script')


def kid(raw_key):
    jwk = '{"crv":"Ed25519","kty":"OKP","x":"%s"}' % b64e(raw_key)
    return b64e(hashlib.sha256(jwk.encode()).digest())


def publisher_keys(values):
    keys = {}
    for value in values:
        raw = b64d(value)
        if len(raw) != 32:
            raise Refused('publisher key must be a raw 32-byte Ed25519 key')
        keys[kid(raw)] = raw
    return keys


def verify_jws(manifest, jws, keys):
    """Verify a detached compact JWS over the exact manifest bytes with a pinned key."""
    if not keys:
        raise Refused('a pinned publisher key is required to check the signature')
    try:
        parts = jws.decode('ascii').split('.')
    except UnicodeDecodeError:
        raise Refused('signature is not ASCII') from None
    if len(parts) != 3 or parts[1] != '':
        raise Refused('signature is not a detached compact JWS')
    header_raw = b64d(parts[0])
    header = strict_json(header_raw)
    if type(header) is not dict or canonical(header) != header_raw or set(header) != {'alg', 'kid', 'typ'} \
            or header['alg'] != 'EdDSA' or header['typ'] != 'tam-release+jws' or header['kid'] not in keys:
        raise Refused('signature header refused or key not pinned')
    signature = b64d(parts[2])
    if len(signature) != 64:
        raise Refused('signature length refused')
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        der = ED25519_SPKI + keys[header['kid']]
        (tmp / 'key.pem').write_text('-----BEGIN PUBLIC KEY-----\n' + base64.b64encode(der).decode()
                                     + '\n-----END PUBLIC KEY-----\n')
        (tmp / 'input').write_bytes((parts[0] + '.' + b64e(manifest)).encode())
        (tmp / 'sig').write_bytes(signature)
        result = subprocess.run(['openssl', 'pkeyutl', '-verify', '-pubin', '-inkey', str(tmp / 'key.pem'),
                                 '-rawin', '-in', str(tmp / 'input'), '-sigfile', str(tmp / 'sig')],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode != 0 or b'Signature Verified Successfully' not in result.stdout:
        raise Refused('signature does not verify over the exact manifest bytes')


def validate(request, files, existing, keys):
    """Semantic checks shared by stage and publish; existing holds the release's current asset bytes."""
    kind, tag = request['kind'], request['tag']
    check_bytes(request['assets'], files, 'staged asset')
    if kind in ATTACH_KINDS:
        check_bytes(request['existing'], existing, 'existing asset')
    if kind == 'runtime-candidate':
        check_manifest(tag, files[MANIFEST], request['assets'])
    elif kind == 'runtime-signature':
        check_manifest(tag, existing[MANIFEST], request['existing'])
        verify_jws(existing[MANIFEST], files[JWS], keys)
    elif kind == 'downloads-archive':
        check_manifest(tag, existing[MANIFEST], request['existing'])
        verify_jws(existing[MANIFEST], existing[JWS], keys)
        if not next(iter(files.values())).startswith(b'\x1f\x8b'):
            raise Refused('downloads archive is not gzip')
    elif kind == 'bootstrap':
        check_bootstrap(tag, request['repository'], files)


def git(root, *args, env=None):
    return subprocess.check_output(['git', '-C', str(root), *args], env=env).decode().strip()


def stage_branch(request):
    return 'release-stage/' + request['kind'] + '/' + request['tag']


def pinned_inputs(values):
    files, pins = {}, {}
    for value in values or []:
        path, _, digest = value.rpartition('=')
        if not path or not re.fullmatch('[0-9a-f]{64}', digest):
            raise Refused('expected PATH=SHA256: ' + value)
        name = Path(path).name
        if name in files:
            raise Refused('duplicate asset name: ' + name)
        data = read_regular(path)
        if sha(data) != digest:
            raise Refused('input differs from its independent pin: ' + path)
        files[name] = data
        pins[name] = {'size': len(data), 'sha256': digest}
    return files, pins


def stage(a):
    clone = Path(a.clone).absolute()
    files, assets = pinned_inputs(a.asset)
    existing, existing_pins = pinned_inputs(a.existing)
    request = dict(format=FORMAT, kind=a.kind, repository=a.repository, tag=a.tag, assets=assets, existing=existing_pins)
    raw = json.dumps(request, sort_keys=True, indent=2).encode() + b'\n'
    request = load_request(raw)
    validate(request, files, existing, publisher_keys(a.publisher_key or []))
    url = git(clone, 'remote', 'get-url', 'origin')
    if not re.fullmatch(r'(git@github\.com:|ssh://git@github\.com/|https://github\.com/)' + re.escape(a.repository) + r'(\.git)?', url):
        raise Refused('clone origin is not ' + a.repository + ': ' + url)
    if git(clone, 'status', '--porcelain', '--untracked-files=all'):
        raise Refused('clone is not clean')
    base = git(clone, 'rev-parse', 'HEAD')
    if base != git(clone, 'rev-parse', a.base_ref):
        raise Refused('clone HEAD is not ' + a.base_ref + '; fetch and check out the current default branch')
    branch = stage_branch(request)
    if subprocess.run(['git', '-C', str(clone), 'rev-parse', '--verify', '--quiet', 'refs/heads/' + branch],
                      stdout=subprocess.DEVNULL).returncode == 0:
        raise Refused('staging branch already exists locally: ' + branch)
    if (clone / STAGE).exists() or (clone / STAGE).is_symlink():
        raise Refused(STAGE + ' already exists in the clone')
    when = git(clone, 'show', '-s', '--format=%cI', base)
    env = dict(os.environ, GIT_AUTHOR_NAME='TAM release staging', GIT_AUTHOR_EMAIL='release-staging@invalid',
               GIT_COMMITTER_NAME='TAM release staging', GIT_COMMITTER_EMAIL='release-staging@invalid',
               GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    git(clone, 'checkout', '-q', '-b', branch)
    (clone / STAGE).mkdir()
    for name, data in sorted({**files, REQUEST: raw}.items()):
        with (clone / STAGE / name).open('xb') as f:
            f.write(data)
        (clone / STAGE / name).chmod(0o644)
    git(clone, 'add', '-f', '--', STAGE)
    git(clone, '-c', 'commit.gpgsign=false', 'commit', '-q', '--no-verify', '-m',
        f'Stage {a.kind} {a.tag}\n\nPublished only by the reviewed publish-staged-release workflow.', env=env)
    check_stage_commit(clone, base, set(files) | {REQUEST})
    commit = git(clone, 'rev-parse', 'HEAD')
    print(json.dumps(dict(branch=branch, commit=commit, base=base, repository=a.repository,
                          request_sha256=sha(raw), assets=assets, existing=existing_pins), sort_keys=True, indent=2))
    print('Staged locally; nothing pushed. After review, push without force:')
    print(f'  git -C {clone} push origin refs/heads/{branch}:refs/heads/{branch}')


def check_stage_commit(root, target, names):
    """The staging commit is a single child of target that only adds files under STAGE."""
    parents = git(root, 'rev-list', '--parents', '-n', '1', 'HEAD').split()
    if len(parents) != 2 or parents[1] != target:
        raise Refused('staging commit must be a single-parent child of the current default branch')
    changes = git(root, 'diff', '--name-status', '--no-renames', 'HEAD^', 'HEAD').splitlines()
    added = set()
    for line in changes:
        status, _, path = line.partition('\t')
        if status != 'A' or not path.startswith(STAGE + '/') or '/' in path[len(STAGE) + 1:]:
            raise Refused('staging commit changes more than new ' + STAGE + ' files: ' + line)
        added.add(path[len(STAGE) + 1:])
    if added != names:
        raise Refused('staging commit file set differs from the request')


def urllib_transport(method, url, headers, data, token):
    if not url.startswith('https://'):
        raise Refused('HTTPS required: ' + url)
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    if token:
        # Unredirected: signed asset redirects must not receive the token.
        req.add_unredirected_header('Authorization', 'Bearer ' + token)
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.status, r.read(MAX_ASSET + 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read(65536)


class GitHub:
    def __init__(self, repository, token=None, api='https://api.github.com', transport=None):
        self.repo, self.token, self.api = repository, token, api
        self.transport = transport or urllib_transport

    def call(self, method, url, body=None, data=None, accept='application/vnd.github+json', content_type=None):
        headers = {'Accept': accept, 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'tam-release-publish'}
        if body is not None:
            data, content_type = json.dumps(body).encode(), 'application/json'
        if content_type:
            headers['Content-Type'] = content_type
        return self.transport(method, url, headers, data, self.token)

    def json(self, method, path, body=None, ok=(200,)):
        status, raw = self.call(method, self.api + '/repos/' + self.repo + path, body=body)
        if status not in ok:
            raise Refused(f'GitHub {method} {path} answered {status}')
        return json.loads(raw) if raw else None

    def releases(self, tag):
        found = []
        for page in range(1, 11):
            items = self.json('GET', f'/releases?per_page=100&page={page}')
            if type(items) is not list:
                raise Refused('release list refused')
            found += [r for r in items if type(r) is dict and r.get('tag_name') == tag]
            if len(items) < 100:
                return found
        raise Refused('too many releases to search exhaustively')

    def tag_exists(self, tag):
        refs = self.json('GET', '/git/matching-refs/tags/' + urllib.parse.quote(tag, safe=''))
        return any(type(r) is dict and r.get('ref') == 'refs/tags/' + tag for r in refs or [])

    def tag_commit(self, tag):
        ref = self.json('GET', '/git/ref/tags/' + urllib.parse.quote(tag, safe=''))
        obj = ref.get('object') or {}
        if obj.get('type') == 'tag':
            obj = self.json('GET', '/git/tags/' + obj['sha']).get('object') or {}
        return obj.get('sha')

    def download(self, asset):
        status, raw = self.call('GET', f'{self.api}/repos/{self.repo}/releases/assets/{asset["id"]}',
                                accept='application/octet-stream')
        if status != 200 or len(raw) > MAX_ASSET:
            raise Refused(f'asset download answered {status}: {asset["name"]}')
        return raw

    def upload(self, release, name, data):
        url = release['upload_url'].split('{', 1)[0] + '?name=' + urllib.parse.quote(name, safe='')
        status, raw = self.call('POST', url, data=data, content_type='application/octet-stream')
        if status != 201:
            raise Refused(f'upload of {name} answered {status}')
        asset = json.loads(raw)
        if asset.get('name') != name or asset.get('size') != len(data):
            raise Refused('uploaded asset metadata differs: ' + name)


def asset_map(release):
    assets = {}
    for a in release.get('assets') or []:
        if a['name'] in assets:
            raise Refused('duplicate asset name in release: ' + a['name'])
        if a.get('state', 'uploaded') != 'uploaded':
            raise Refused('incomplete asset upload needs coordinator inspection: ' + a['name'])
        assets[a['name']] = a
    return assets


def fetch_matching(gh, release, pins):
    """Download the named assets and check them against their pins."""
    assets, data = asset_map(release), {}
    for name, pin in pins.items():
        a = assets[name]
        digest = a.get('digest')
        if a['size'] != pin['size'] or (digest is not None and digest != 'sha256:' + pin['sha256']):
            raise Refused('published asset differs from pin: ' + name)
        data[name] = gh.download(a)
        if len(data[name]) != pin['size'] or sha(data[name]) != pin['sha256']:
            raise Refused('published asset bytes differ from pin: ' + name)
    return data


def release_body(request, target):
    """Release text naming the exact request and staging base; it marks drafts created by this request."""
    return (BODY[request['kind']].format(tag=request['tag']) + '\n\nStaging request SHA-256: '
            + sha(canonical(request)) + '\nStaging base commit: ' + target)


def check_own_draft(release, request, target):
    """A draft is resumed or published only if it carries exactly what this request creates."""
    expected = dict(tag_name=request['tag'], name=request['tag'], body=release_body(request, target),
                    target_commitish=target, draft=True, prerelease=True)
    differing = sorted(k for k, v in expected.items() if release.get(k) != v)
    if differing:
        raise Refused('draft with tag ' + request['tag'] + ' was not created by this request (' + ', '.join(differing)
                      + ' differ); nothing changed, inspect it')


def publish_new(gh, request, files, target):
    tag, pins = request['tag'], request['assets']
    found = gh.releases(tag)
    if len(found) > 1:
        raise Refused('several releases carry tag ' + tag)
    if found and not found[0]['draft']:
        release = found[0]
        if release.get('prerelease') is not True or release.get('tag_name') != tag:
            raise Refused('the published release with tag ' + tag + ' is not a prerelease; nothing changed')
        if set(asset_map(release)) != set(pins):
            raise Refused('a published release with tag ' + tag + ' has other assets; nothing changed')
        if gh.tag_commit(tag) != target:
            raise Refused('published tag ' + tag + ' does not point to the staging base commit; nothing changed')
        fetch_matching(gh, release, pins)
        return release, 'already published with identical assets; nothing changed'
    # Without a published release the tag must not exist: publishing a draft would reuse a foreign tag.
    if gh.tag_exists(tag):
        raise Refused('tag ' + tag + ' already exists without a published release; nothing changed')
    if found:
        release = found[0]  # Resume only this request's own interrupted draft with an exact, verified subset.
        check_own_draft(release, request, target)
        present = set(asset_map(release))
        if not present <= set(pins):
            raise Refused('existing draft has unexpected assets; inspect it')
        fetch_matching(gh, release, {n: pins[n] for n in present})
    else:
        release = gh.json('POST', '/releases', dict(tag_name=tag, target_commitish=target, name=tag,
                                                    body=release_body(request, target),
                                                    draft=True, prerelease=True), ok=(201,))
        check_own_draft(release, request, target)
        present = set()
    for name in sorted(set(pins) - present):
        gh.upload(release, name, files[name])
    # Recheck immediately before publication; a writer outside this workflow can still race the PATCH.
    release = gh.json('GET', f'/releases/{release["id"]}')
    check_own_draft(release, request, target)
    if set(asset_map(release)) != set(pins):
        raise Refused('draft asset set differs after upload; left unpublished')
    fetch_matching(gh, release, pins)
    if gh.tag_exists(tag):
        raise Refused('tag ' + tag + ' appeared before publication; draft left unpublished, inspect it')
    release = gh.json('PATCH', f'/releases/{release["id"]}', dict(draft=False, prerelease=True, target_commitish=target))
    if release.get('draft') is not False or release.get('prerelease') is not True or release.get('tag_name') != tag:
        raise Refused('release state after publication differs')
    if gh.tag_commit(tag) != target:
        raise Refused('published tag does not point to the staging base commit; inspect release ' + tag)
    return release, 'published'


def publish_attach(gh, request, files, keys):
    tag = request['tag']
    found = gh.releases(tag)
    if len(found) != 1 or found[0]['draft'] or found[0].get('prerelease') is not True:
        raise Refused('exactly one published prerelease with tag ' + tag + ' is required')
    release = found[0]
    present = set(asset_map(release))
    complete = {**request['existing'], **request['assets']}
    if present == set(complete):
        data = fetch_matching(gh, release, complete)
        validate(request, {n: data[n] for n in request['assets']}, {n: data[n] for n in request['existing']}, keys)
        return release, 'already attached with identical bytes; nothing changed'
    if present != set(request['existing']):
        raise Refused('release assets differ from the expected existing set; nothing changed')
    existing = fetch_matching(gh, release, request['existing'])
    validate(request, files, existing, keys)
    for name in sorted(request['assets']):
        gh.upload(release, name, files[name])
    release = gh.json('GET', f'/releases/{release["id"]}')
    if set(asset_map(release)) != set(complete):
        raise Refused('release asset set differs after upload')
    fetch_matching(gh, release, complete)
    return release, 'attached'


def stage_files(stage_dir, request):
    names = {p.name for p in Path(stage_dir).iterdir()}
    if names != set(request['assets']) | {REQUEST}:
        raise Refused('staging directory inventory differs from the request')
    return {n: read_regular(Path(stage_dir) / n) for n in request['assets']}


def publish(a):
    token = os.environ.get('GITHUB_TOKEN')
    if not token:
        raise Refused('GITHUB_TOKEN is required')
    stage_dir = Path(a.stage_root) / STAGE
    request = load_request(read_regular(stage_dir / REQUEST))
    if request['repository'] != a.repository:
        raise Refused('request repository differs from the workflow repository')
    if a.ref != 'refs/heads/' + stage_branch(request):
        raise Refused('push ref differs from release-stage/<kind>/<tag> of the request')
    if not re.fullmatch('[0-9a-f]{40}', a.target):
        raise Refused('target must be a full commit')
    files = stage_files(stage_dir, request)
    check_stage_commit(a.stage_root, a.target, set(files) | {REQUEST})
    keys = publisher_keys(a.publisher_key or [])
    gh = GitHub(a.repository, token, a.api)
    if request['kind'] in CREATE_KINDS:
        validate(request, files, None, keys)
        release, outcome = publish_new(gh, request, files, a.target)
    else:
        release, outcome = publish_attach(gh, request, files, keys)
    print(json.dumps(dict(outcome=outcome, tag=request['tag'], release_id=release['id'], url=release.get('html_url'),
                          assets={n: x['size'] for n, x in sorted(asset_map(release).items())}), sort_keys=True, indent=2))
    # The staging branch is kept: GitHub's ref deletion cannot be conditioned on the expected commit.
    print('staging branch kept: ' + stage_branch(request))


def verify(a):
    if not REPOSITORY.fullmatch(a.repository):
        raise Refused('repository refused')
    pins = {}
    for value in a.asset:
        name, _, digest = value.rpartition('=')
        if not name or '/' in name or not re.fullmatch('[0-9a-f]{64}', digest) or name in pins:
            raise Refused('expected unique NAME=SHA256: ' + value)
        pins[name] = digest
    gh = GitHub(a.repository, None, a.api)
    release = gh.json('GET', '/releases/tags/' + urllib.parse.quote(a.tag, safe=''))
    if release.get('draft') is not False or release.get('prerelease') is not True or release.get('tag_name') != a.tag:
        raise Refused('release is not a published prerelease with this tag')
    assets = asset_map(release)
    if set(assets) != set(pins):
        raise Refused('published asset set differs: ' + ', '.join(sorted(set(assets) ^ set(pins))))
    prefix = f'https://github.com/{a.repository}/releases/download/{a.tag}/'
    for name, digest in sorted(pins.items()):
        x = assets[name]
        if x.get('digest') is not None and x['digest'] != 'sha256:' + digest:
            raise Refused('reported digest differs: ' + name)
        if not x['browser_download_url'].startswith(prefix):
            raise Refused('unexpected download URL: ' + name)
        status, data = gh.call('GET', x['browser_download_url'], accept='application/octet-stream')
        if status != 200 or len(data) != x['size'] or sha(data) != digest:
            raise Refused('downloaded bytes differ: ' + name)
        print(f'{digest}  {x["size"]}  {x["browser_download_url"]}')
    print(f'OK: {a.repository} {a.tag} has exactly {len(pins)} pinned assets')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    s = sub.add_parser('stage')
    s.add_argument('--kind', required=True, choices=CREATE_KINDS + ATTACH_KINDS)
    s.add_argument('--tag', required=True)
    s.add_argument('--repository', required=True)
    s.add_argument('--clone', required=True, help='clean clone of the public repository')
    s.add_argument('--base-ref', default='refs/remotes/origin/main')
    s.add_argument('--asset', action='append', required=True, help='PATH=SHA256 of a new asset (repeat)')
    s.add_argument('--existing', action='append', help='PATH=SHA256 of an asset already on the release (attach kinds)')
    s.add_argument('--publisher-key', action='append', help='raw base64url Ed25519 publisher key (signature kinds)')
    s.set_defaults(fn=stage)
    s = sub.add_parser('publish')
    s.add_argument('--stage-root', required=True, help='checkout of the pushed staging commit')
    s.add_argument('--repository', required=True)
    s.add_argument('--ref', required=True)
    s.add_argument('--target', required=True, help='current default branch commit (staging parent)')
    s.add_argument('--publisher-key', action='append')
    s.add_argument('--api', default='https://api.github.com')
    s.set_defaults(fn=publish)
    s = sub.add_parser('verify')
    s.add_argument('--repository', required=True)
    s.add_argument('--tag', required=True)
    s.add_argument('--asset', action='append', required=True, help='NAME=SHA256 (repeat; the exact asset set)')
    s.add_argument('--api', default='https://api.github.com')
    s.set_defaults(fn=verify)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == '__main__':
    try:
        main()
    except (Refused, OSError, subprocess.CalledProcessError, KeyError, ValueError) as error:
        sys.exit('release publication refused: ' + str(error))
