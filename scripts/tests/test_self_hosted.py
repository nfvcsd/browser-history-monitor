import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / 'scripts/build_self_hosted.py'
spec = importlib.util.spec_from_file_location('builder', SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.key = self.root / 'fixture.pem'
        subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', str(self.key)],
                       check=True, capture_output=True)
        self.public, self.extension_id = builder.key_identity(self.key)

    def run_builder(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), '--key', str(self.key), *args],
                              capture_output=True, text=True)

    def test_identity_is_stable(self):
        result = self.run_builder('--identity-only')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), self.extension_id)
        self.assertRegex(self.extension_id, r'^[a-p]{32}$')

    def test_mismatched_key_fails_before_build(self):
        result = self.run_builder('--expected-id', 'a' * 32, '--chrome', '/missing',
                                  '--oauth-client-id', '123-fixture.apps.googleusercontent.com')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('does not match', result.stderr)

    def test_real_chrome_package(self):
        chrome = os.environ.get('CHROME_BIN') or shutil.which('google-chrome')
        if not chrome:
            self.skipTest('Set CHROME_BIN to run real CRX3 packaging')
        out = self.root / 'release'
        args = ['--chrome', chrome, '--expected-id', self.extension_id,
                '--oauth-client-id', '123-fixture.apps.googleusercontent.com',
                '--api-origin', 'https://history.example.com', '--repository', 'school/history',
                '--output', str(out)]
        result = self.run_builder(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = (out / 'browser-history-agent.crx').read_bytes()
        magic, version, size = struct.unpack('<4sII', data[:12])
        self.assertEqual((magic, version), (b'Cr24', 3))
        with zipfile.ZipFile(io.BytesIO(data[12 + size:])) as z:
            manifest = json.loads(z.read('manifest.json'))
            self.assertEqual(manifest['update_url'], 'https://school.github.io/history/updates.xml')
            self.assertEqual(manifest['oauth2']['client_id'], '123-fixture.apps.googleusercontent.com')
            self.assertEqual(set(manifest['host_permissions']), {'https://history.example.com/*', 'https://api64.ipify.org/*'})
            self.assertIn('device-auth.js', z.namelist())
            self.assertFalse(any(name.endswith('.pem') or '/tests/' in name or name.endswith('.env') for name in z.namelist()))
        tree = ET.parse(out / 'pages/updates.xml')
        ns = {'g': 'http://www.google.com/update2/response'}
        app = tree.find('g:app', ns)
        self.assertEqual(app.attrib['appid'], self.extension_id)
        update = app.find('g:updatecheck', ns)
        self.assertEqual(update.attrib['version'], manifest['version'])
        self.assertIn('/releases/download/extension-v' + manifest['version'] + '/', update.attrib['codebase'])
        original = data
        self.assertNotEqual(self.run_builder(*args).returncode, 0)
        self.assertEqual((out / 'browser-history-agent.crx').read_bytes(), original)
