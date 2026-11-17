"""Verify that platform integration preserves the supplied offline replay."""
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCENE = ROOT / 'uav-inspection-ui' / 'public' / 'maize'


class MaizePackageTests(unittest.TestCase):
    def test_original_replay_is_preserved_byte_for_byte(self):
        manifest = json.loads((SCENE / 'offline_package_manifest.json').read_text())
        html = (SCENE / 'index.html').read_bytes()
        bridge = b'<script src="./platform-bridge.js"></script>'
        layout = b'<link rel="stylesheet" href="./platform-layout.css">'
        self.assertEqual(html.count(bridge), 1)
        self.assertEqual(html.count(layout), 1)
        data_prefix = b'window.INSPECTION_DATA='
        data = (SCENE / 'data.js').read_bytes()
        self.assertTrue(data.startswith(data_prefix))
        self.assertTrue(data.endswith(b';\n'))
        scenes = []
        script_names = ['data']
        for count in (1, 2, 3):
            parts = sorted(SCENE.glob(f'scene-{count}-part-*.js'))
            self.assertTrue(parts)
            strings = []
            for part in parts:
                script_names.append(part.stem)
                match = re.search(r'\.push\((.*)\);\n', part.read_text())
                self.assertIsNotNone(match)
                strings.append(json.loads(match.group(1)))
            scenes.append(f'"{count}":'.encode() + ''.join(strings).encode())
        data = data[:-2].replace(b'"scenes":{}', b'"scenes":{' + b','.join(scenes) + b'}', 1)
        script_names.append('app')
        tags = b''.join(f'<script src="./{name}.js"></script>'.encode() for name in script_names)
        self.assertEqual(html.count(tags), 1)
        original = html.replace(bridge, b'', 1).replace(layout, b'', 1).replace(
            tags, b'<script>' + data + (SCENE / 'app.js').read_bytes() + b'</script>', 1)
        self.assertEqual(len(original), manifest['html_bytes'])
        self.assertEqual(hashlib.sha256(original).hexdigest(), manifest['html_sha256'])

    def test_source_delivery_includes_entire_scene_and_licenses(self):
        spec = importlib.util.spec_from_file_location('maize_delivery', ROOT / 'scripts' / 'build_delivery.py')
        delivery = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = delivery
        spec.loader.exec_module(delivery)
        expected = {p.relative_to(ROOT).as_posix() for p in SCENE.rglob('*') if p.is_file()}
        packaged = {e.path for e in delivery.collect_files(ROOT, include_data=False) if e.category == 'app'}
        self.assertTrue(expected)
        self.assertEqual(expected - packaged, set())
        self.assertIn('uav-inspection-ui/public/maize/素材来源与许可/数据许可.md', packaged)


if __name__ == '__main__':
    unittest.main()
