"""Build a signed CRX3 and GitHub Pages update feed using an existing key."""
import argparse
import base64
import hashlib
import io
import json
import re
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def key_identity(key):
    public = subprocess.check_output(
        ['openssl', 'pkey', '-in', str(key), '-pubout', '-outform', 'DER'],
        stderr=subprocess.DEVNULL,
    )
    extension_id = ''.join(chr(97 + int(c, 16)) for c in hashlib.sha256(public).hexdigest()[:32])
    return public, extension_id


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--key', type=Path, required=True)
    p.add_argument('--identity-only', action='store_true')
    p.add_argument('--chrome', type=Path)
    p.add_argument('--expected-id')
    p.add_argument('--oauth-client-id')
    p.add_argument('--repository', default='nfvcsd/browser-history-monitor')
    p.add_argument('--api-origin', action='append')
    p.add_argument('--managed-https', action='store_true')
    p.add_argument('--output', type=Path, default=ROOT / 'dist/self-hosted')
    a = p.parse_args()
    public, extension_id = key_identity(a.key.resolve())
    if a.identity_only:
        print(extension_id)
        return
    if not a.chrome or not a.oauth_client_id or not a.expected_id:
        p.error('Build requires --chrome, --oauth-client-id and --expected-id')
    if a.expected_id != extension_id:
        p.error('Signing key does not match expected extension ID')
    if not re.fullmatch(r'[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+', a.repository):
        p.error('Expected repository OWNER/NAME')
    if bool(a.api_origin) == a.managed_https:
        p.error('Choose --api-origin or --managed-https')
    if a.output.exists():
        p.error('Output already exists; choose a new directory')
    owner, repo = a.repository.split('/')
    update_url = f'https://{owner.lower()}.github.io/{repo}/updates.xml'
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        archive = tmp / 'extension.zip'
        command = [sys.executable, str(ROOT / 'scripts/package_extension.py'),
                   '--oauth-client-id', a.oauth_client_id, '--output', str(archive)]
        if a.managed_https:
            command.append('--managed-https')
        for origin in a.api_origin or []:
            command += ['--api-origin', origin]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
        stage = tmp / 'extension'
        with zipfile.ZipFile(archive) as z:
            z.extractall(stage)
        manifest = json.loads((stage / 'manifest.json').read_text())
        version = manifest['version']
        if (not re.fullmatch(r'(0|[1-9]\d*)(\.(0|[1-9]\d*)){0,3}', version)
                or any(int(v) > 65535 for v in version.split('.'))
                or not any(int(v) for v in version.split('.'))):
            p.error('Invalid Chrome version')
        manifest.update(update_url=update_url, key=base64.b64encode(public).decode())
        (stage / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        subprocess.run([str(a.chrome.resolve()), '--headless=new', '--no-sandbox',
                        f'--user-data-dir={tmp}/profile', f'--pack-extension={stage}',
                        f'--pack-extension-key={a.key.resolve()}'], check=True,
                       timeout=60, stdout=subprocess.DEVNULL)
        crx = stage.with_suffix('.crx').read_bytes()
        magic, crx_version, size = struct.unpack('<4sII', crx[:12])
        if magic != b'Cr24' or crx_version != 3:
            raise ValueError('Expected a signed CRX3')
        with zipfile.ZipFile(io.BytesIO(crx[12 + size:])) as z:
            if json.loads(z.read('manifest.json')) != manifest:
                raise ValueError('Packed manifest mismatch')
        a.output.mkdir(parents=True)
        (a.output / 'browser-history-agent.crx').write_bytes(crx)
    pages = a.output / 'pages'
    pages.mkdir()
    ns = 'http://www.google.com/update2/response'
    ET.register_namespace('', ns)
    root = ET.Element(f'{{{ns}}}gupdate', protocol='2.0')
    app = ET.SubElement(root, f'{{{ns}}}app', appid=extension_id)
    ET.SubElement(app, f'{{{ns}}}updatecheck', version=version,
                  codebase=f'https://github.com/{a.repository}/releases/download/extension-v{version}/browser-history-agent.crx')
    ET.ElementTree(root).write(pages / 'updates.xml', encoding='utf-8', xml_declaration=True)
    (pages / '.nojekyll').touch()
    (a.output / 'extension-id.txt').write_text(extension_id + '\n')
    (a.output / 'SHA256SUMS').write_text(hashlib.sha256(crx).hexdigest() + '  browser-history-agent.crx\n')
    print(f'Built {version}; extension ID {extension_id}; update URL {update_url}')


if __name__ == '__main__':
    main()
