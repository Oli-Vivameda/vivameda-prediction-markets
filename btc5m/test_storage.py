import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import patch
from capture import Capture, load_capture_settings, verify_capture
from storage_migration import copy_capture, validate_destination, write_config


class StorageTests(unittest.TestCase):
    def database(self,path):
        c=Capture(path,min_free=0)
        for i in range(10):c.offer('reference_tick',{'price':83000+i})
        deadline=time.monotonic()+2
        while c.stored<10 and time.monotonic()<deadline:time.sleep(.01)
        c.close();self.assertEqual(c.stored,10)

    def test_default_settings_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            s=load_capture_settings(Path(d)/'paper.sqlite3')
            self.assertEqual(s['max_bytes'],2*1024**3);self.assertFalse(s['configured'])

    def test_consistent_copy_preserves_source_and_chain(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'source.db';dst=Path(d)/'destination.db';self.database(src)
            r=copy_capture(src,dst)
            self.assertEqual(r['copied_events'],10);self.assertTrue(src.exists())
            self.assertEqual(verify_capture(dst),10);self.assertEqual(dst.stat().st_mode&0o777,0o600)

    def test_existing_destination_not_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            dst=Path(d)/'dst';dst.write_text('preserve')
            with self.assertRaises(ValueError):copy_capture(Path(d)/'missing',dst)
            self.assertEqual(dst.read_text(),'preserve')

    def test_corrupt_chain_refused_without_publishing_copy(self):
        with tempfile.TemporaryDirectory() as d:
            src=Path(d)/'source.db';dst=Path(d)/'destination.db';self.database(src)
            with sqlite3.connect(src) as db:db.execute("UPDATE feed_batches SET digest='changed'")
            with self.assertRaises(ValueError):copy_capture(src,dst)
            self.assertFalse(dst.exists());self.assertTrue(src.exists())

    def test_private_config_and_configured_limits(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);data=root/'data';volume=root/'volume';data.mkdir();volume.mkdir(mode=0o700)
            cfg=write_config(data,volume/'capture.sqlite3',100*1024**3,50*1024**3)
            self.assertEqual(cfg.stat().st_mode&0o777,0o600)
            settings=load_capture_settings(data/'paper.sqlite3')
            self.assertTrue(settings['configured']);self.assertEqual(settings['max_bytes'],100*1024**3)

    def test_missing_volume_never_falls_back_to_root(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);volume=root/'volume';volume.mkdir(mode=0o700)
            cfg=write_config(root,volume/'capture.sqlite3',100*1024**3,50*1024**3)
            volume.rmdir()
            with self.assertRaises(ValueError):load_capture_settings(root/'paper.sqlite3')

    def test_changed_device_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);v=root/'volume';v.mkdir(mode=0o700)
            cfg=write_config(root,v/'capture.sqlite3',100*1024**3,50*1024**3)
            c=json.loads(cfg.read_text());c['device']+=1;cfg.write_text(json.dumps(c))
            with self.assertRaises(ValueError):load_capture_settings(root/'paper.sqlite3')

    def test_same_filesystem_destination_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);src=root/'source.db';src.write_text('x');target=root/'target';target.mkdir(mode=0o700)
            with self.assertRaises(ValueError):validate_destination(target,src,0)

    def test_existing_config_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);v=p/'volume';v.mkdir(mode=0o700)
            cfg=write_config(p,v/'capture.sqlite3',100*1024**3,50*1024**3)
            old=cfg.read_bytes()
            with self.assertRaises(ValueError):write_config(p,v/'other.sqlite3',1,0)
            self.assertEqual(old,cfg.read_bytes())


if __name__=='__main__':unittest.main()
