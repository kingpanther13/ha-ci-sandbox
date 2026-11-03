import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.error


SOURCE = Path(__file__).resolve().parents[1] / 'ha_ci_sandbox/instances.py'
spec = importlib.util.spec_from_file_location('instances', SOURCE)
instances = importlib.util.module_from_spec(spec) if SOURCE.exists() else None
if instances:
    spec.loader.exec_module(instances)


class InstanceProfiles(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(instances, 'Instance profile support is missing')

    def test_existing_options_keep_all_legacy_paths(self):
        plans = instances.resolve({'instances': 2})
        self.assertEqual([(p['data_dir'], p['work_dir'], p['cache_dir']) for p in plans], [
            ('/data/hub', '/data/work', '/data/bundle'),
            ('/data/hub-2', '/data/work-2', '/data/bundle')])

    def test_versions_select_separate_bundles_and_persistent_databases(self):
        plans = instances.resolve({'instances': 2, 'instance_profiles': [
            {'instance': 1, 'profile': 'v1', 'bundle_dir': '/share/app-v1'},
            {'instance': 2, 'profile': 'v2', 'bundle_dir': '/share/app-v2'}]})
        self.assertEqual(plans[0]['data_dir'], '/data/profiles/v1/instance-1/hub')
        self.assertEqual(plans[1]['data_dir'], '/data/profiles/v2/instance-2/hub')
        self.assertEqual(plans[1]['bundle_dir'], '/share/app-v2')
        self.assertNotEqual(plans[1]['cache_dir'], '/data/bundle')
        self.assertEqual(instances.resolve({'instance_profiles': [
            {'instance': 1, 'profile': 'v1'}]})[0]['data_dir'], plans[0]['data_dir'])

    def test_same_profile_never_shares_database_between_instances(self):
        plans = instances.resolve({'instances': 2, 'instance_profiles': [
            {'instance': n, 'profile': 'preview'} for n in (1, 2)]})
        self.assertNotEqual(plans[0]['data_dir'], plans[1]['data_dir'])

    def test_custom_directory_does_not_inherit_shared_url(self):
        plan = instances.resolve({'bundle_url': 'https://example.com/stable.tgz',
            'instance_profiles': [{'instance': 1, 'profile': 'preview',
                                   'bundle_dir': '/share/preview'}]})[0]
        self.assertEqual(plan['bundle_url'], '')

    def test_url_only_override_does_not_select_shared_directory(self):
        plan = instances.resolve({'instance_profiles': [{'instance': 1, 'profile': 'preview',
            'bundle_url': 'https://example.com/preview.tgz'}]})[0]
        self.assertEqual(plan['bundle_dir'], '')

    def test_invalid_and_duplicate_profiles_are_rejected(self):
        for rows in ([{'instance': 1, 'profile': '../other'}],
                     [{'instance': 1, 'profile': 'x'}, {'instance': 1, 'profile': 'y'}],
                     [{'instance': 2, 'profile': 'x'}],
                     [{'instance': True, 'profile': 'x'}],
                     [{'instance': 1, 'profile': 'x', 'bundle_sha256': 'bad'}]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                instances.resolve({'instance_profiles': rows})

    def test_changing_download_source_uses_a_new_cache(self):
        def plan(url):
            return instances.resolve({'instance_profiles': [{'instance': 1,
                'profile': 'preview', 'bundle_url': url}]})[0]
        self.assertNotEqual(plan('https://example.com/a.tgz')['cache_dir'],
                            plan('https://example.com/b.tgz')['cache_dir'])

    def test_null_optional_bundle_options_are_accepted(self):
        plan = instances.resolve({'bundle_url': None, 'bundle_sha256': None,
            'instance_profiles': [{'instance': 1, 'profile': 'preview',
                                   'bundle_sha256': None}]})[0]
        self.assertEqual(plan['bundle_sha256'], '')
        self.assertEqual(plan['bundle_url'], '')

    def test_null_profile_checksum_preserves_inherited_verification(self):
        checksum = 'a' * 64
        plans = instances.resolve({'instances': 2, 'bundle_sha256': checksum,
            'bundle_url': 'https://example.com/shared.tgz', 'instance_profiles': [
                {'instance': 1, 'profile': 'inherited', 'bundle_sha256': None},
                {'instance': 2, 'profile': 'custom', 'bundle_sha256': None,
                 'bundle_url': 'https://example.com/custom.tgz'}]})
        self.assertEqual(plans[0]['bundle_sha256'], checksum)
        self.assertEqual(plans[1]['bundle_sha256'], '')

    def test_download_failure_keeps_other_instances_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plans = instances.resolve({'instances': 2, 'instance_profiles': [
                {'instance': 2, 'profile': 'preview', 'bundle_url': 'https://example.com/missing.tgz'}]})
            for plan in plans:
                for key in ('data_dir', 'work_dir', 'cache_dir'):
                    plan[key] = str(root / str(plan['instance']) / key)
                plan['bundle_dir'] = ''
            with patch.object(instances.urllib.request, 'urlopen', side_effect=urllib.error.URLError('offline')):
                instances.prepare_instances(plans, root / 'instances.json')
            self.assertEqual(len(json.loads((root / 'instances.json').read_text())), 2)
            self.assertNotIn('https://example.com/missing.tgz', (root / 'instances.json').read_text())
            self.assertTrue(Path(plans[0]['data_dir']).is_dir())
            self.assertFalse(instances.has_bundle(plans[1]['cache_dir']))

    def test_valid_bundle_recovers_incomplete_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); destination = root / 'bundle'; destination.mkdir()
            (destination / 'partial').write_text('interrupted download')
            instances.extract_bundle(self.archive(root), destination)
            self.assertTrue(instances.has_bundle(destination))
            self.assertFalse((destination / 'partial').exists())

    def archive(self, root, unsafe=False):
        path = root / 'bundle.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            for name, body in [('wrapper/app.jar', b'application'),
                               ('wrapper/launcher/start.sh', b'#!/bin/sh\nexit 0\n')]:
                info = tarfile.TarInfo(name); info.size = len(body)
                archive.addfile(info, io.BytesIO(body))
            if unsafe:
                info = tarfile.TarInfo('../escaped'); info.size = 1
                archive.addfile(info, io.BytesIO(b'x'))
        return path

    def test_bundle_extraction_accepts_wrapper_and_preserves_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); database = root / 'hub.db'; database.write_text('retained')
            instances.extract_bundle(self.archive(root), root / 'bundle')
            self.assertEqual((root / 'bundle/app.jar').read_bytes(), b'application')
            self.assertEqual(database.read_text(), 'retained')

    def test_traversal_archive_never_writes_outside_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ValueError):
                instances.extract_bundle(self.archive(root, unsafe=True), root / 'bundle')
            self.assertFalse((root / 'escaped').exists())
            self.assertFalse((root / 'bundle').exists())


if __name__ == '__main__':
    unittest.main()
