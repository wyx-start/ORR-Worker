"""Immutable job isolation and two-phase file safety, without Qt."""
from copy import deepcopy
from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import patch
from application.workspace import Workspace,State
from application.tasks import snapshot,execute,workspace_stamp,prepare_file,atomic_write,JobCancelled
from migration_fixtures import workspace


class TaskPublicationTests(unittest.TestCase):
    def setUp(self):
        traces,configs,settings=workspace();self.w=Workspace(State(traces=traces,configs=configs,settings=settings))
        self.ident=next(iter(traces))
    def test_snapshot_is_immutable_and_detached_from_live_arrays_and_records(self):
        job=snapshot(self.w,'parameters',{})
        before=pickle.loads(job.state);self.w.state.configs[self.ident]['pH']=0;self.w.state.traces[self.ident].values[0,0]=99
        restored=pickle.loads(job.state)
        self.assertEqual(restored['configs'][self.ident]['pH'],13);self.assertNotEqual(restored['traces'][self.ident].values[0,0],99)
        with self.assertRaises(Exception):job.operation='import'

    def test_worker_project_does_not_apply_live_draft_or_publish_target(self):
        self.w.stage_config_updates('conditions',{self.ident:{'collection_efficiency':.4}})
        before=deepcopy(self.w.state.configs)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'project.orrproj';path.write_bytes(b'original')
            result=execute(snapshot(self.w,'project',{'target':str(path)}))
            self.assertEqual(path.read_bytes(),b'original');self.assertEqual(self.w.state.configs,before);self.assertTrue(self.w.has_draft())
            self.assertEqual(result['state'].configs[self.ident]['collection_efficiency'],.4)
            result['prepared'].discard();self.assertEqual(list(Path(folder).glob('.orr-worker-*')),[])

    def test_atomic_replace_failure_preserves_original_and_removes_only_own_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'existing.csv';path.write_bytes(b'original');other=Path(folder)/'unrelated.tmp';other.write_bytes(b'keep')
            with patch('application.tasks.os.replace',side_effect=PermissionError('read-only')):
                with self.assertRaises(PermissionError):atomic_write(path,b'new result')
            self.assertEqual(path.read_bytes(),b'original');self.assertEqual(other.read_bytes(),b'keep')
            self.assertEqual(list(Path(folder).glob('.orr-worker-*')),[])

    def test_cancelled_job_never_produces_target_or_applies_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'cancelled.json'
            with self.assertRaises(JobCancelled):execute(snapshot(self.w,'parameters',{'target':str(path)}),lambda:True)
            self.assertFalse(path.exists());self.assertEqual(self.w.state.revision,0)

    def test_mid_write_cancellation_cleans_temp_and_keeps_existing_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'existing.bin';path.write_bytes(b'original');calls=[0]
            def checkpoint():
                calls[0]+=1
                if calls[0]>2:raise JobCancelled()
            with self.assertRaises(JobCancelled):prepare_file(path,b'x'*(3*1024*1024),checkpoint)
            self.assertEqual(path.read_bytes(),b'original');self.assertEqual(list(Path(folder).glob('.orr-worker-*')),[])

    def test_successful_publication_replaces_complete_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'中文 file.csv';path.write_bytes(b'old');prepared=prepare_file(path,b'complete')
            self.assertEqual(path.read_bytes(),b'old');prepared.publish();self.assertEqual(path.read_bytes(),b'complete')

    def test_model_byte_signatures_are_hashed_and_invalidate_stamp(self):
        self.w.state.results['kl']={'revision':0,'selected':[self.ident],'input_signature':b'first'}
        first=workspace_stamp(self.w);self.w.state.results['kl']['input_signature']=b'second'
        self.assertNotEqual(first,workspace_stamp(self.w))

    def test_background_worker_uses_old_snapshot_when_live_state_changes(self):
        job=snapshot(self.w,'parameters',{});self.w.state.configs[self.ident]['pH']=12.
        result=execute(job);self.assertEqual(result['state'].configs[self.ident]['pH'],13.)
        self.assertEqual(self.w.state.configs[self.ident]['pH'],12.)
