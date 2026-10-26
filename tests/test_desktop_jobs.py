"""Qt responsiveness, stale-result rejection, cancellation and save/close safety."""
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
QT=importlib.util.find_spec('PySide6') is not None


def delayed(job,cancelled,progress):
    from application.tasks import execute,JobCancelled
    for index in range(30):
        if cancelled():raise JobCancelled()
        time.sleep(.005)
    return execute(job,cancelled,progress)


@unittest.skipUnless(QT,'Install requirements/desktop.txt for native job acceptance')
class DesktopJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from migration_fixtures import workspace
        from application.workspace import Workspace,State
        from desktop.window import MainWindow
        traces,configs,settings=workspace();self.w=Workspace(State(traces=traces,configs=configs,settings=settings))
        self.ident=next(iter(traces));self.win=MainWindow(self.w);self.win.force_close=True;self.events=[]
        self.win.jobs.accepted.connect(lambda result:self.events.append('accepted'))
        self.win.jobs.discarded.connect(lambda message:self.events.append('discarded'))
        self.win.jobs.failed.connect(lambda message:self.events.append(('failed',message)))
        self.addCleanup(self.cleanup)
    def cleanup(self):
        from desktop.jobs import wait_for_idle
        if self.win.jobs.busy:self.win.jobs.cancel();wait_for_idle(self.win.jobs)
        self.win.force_close=True;self.win.close()
    def wait(self):
        from desktop.jobs import wait_for_idle
        wait_for_idle(self.win.jobs)

    def test_event_loop_remains_responsive_and_acceptance_runs_on_main_thread(self):
        from PySide6.QtCore import QTimer,QThread
        ticks=[];threads=[];timer=QTimer();timer.setInterval(2);timer.timeout.connect(lambda:ticks.append(1));timer.start()
        self.win.jobs.accepted.connect(lambda result:threads.append(QThread.currentThread()==self.app.thread()))
        self.win.jobs.start('parameters',{},executor=delayed);self.wait();timer.stop()
        self.assertGreater(len(ticks),5);self.assertEqual(threads,[True]);self.assertIn('accepted',self.events)

    def test_scientific_edit_discards_return_and_does_not_replace_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'keep.json';path.write_bytes(b'original')
            self.win.jobs.start('parameters',{'target':str(path)},executor=delayed)
            self.w.stage_config_updates('conditions',{self.ident:{'collection_efficiency':.4}});self.wait()
            self.assertIn('discarded',self.events);self.assertEqual(path.read_bytes(),b'original')
            self.assertEqual(self.w.state.configs[self.ident]['collection_efficiency'],.369);self.assertTrue(self.w.has_draft())
            self.assertEqual(list(Path(directory).glob('.orr-worker-*')),[])

    def test_cancel_does_not_publish_file_or_commit_pending_config(self):
        self.w.stage_config_updates('conditions',{self.ident:{'collection_efficiency':.4}})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cancel.orrproj'
            self.win.jobs.start('project',{'target':str(path)},executor=delayed);self.win.jobs.cancel();self.wait()
            self.assertFalse(path.exists());self.assertTrue(self.w.has_draft());self.assertEqual(self.w.state.configs[self.ident]['collection_efficiency'],.369)
            self.assertIn('discarded',self.events)

    def test_uncommitted_text_is_preserved_and_invalidates_old_job(self):
        from PySide6.QtTest import QTest
        self.win.show();self.app.processEvents();field=self.win.fields['pH'];field.setFocus();field.selectAll()
        self.win.jobs.start('parameters',{},executor=delayed);QTest.keyClicks(field,'12');self.wait()
        self.assertEqual(field.text(),'12');self.assertEqual(self.w.state.configs[self.ident]['pH'],13.)
        self.assertIn('discarded',self.events)

    def test_other_analysis_input_change_cannot_resurrect_old_results(self):
        self.w.state.results['rrde']={'revision':0,'input_signature':b'old','selected':[self.ident]}
        self.w.set_export('rrde_plot.csv',b'old','text/csv')
        self.win.jobs.start('parameters',{},executor=delayed)
        self.win.analyses['rrde'].input_changed();self.wait()
        self.assertIn('discarded',self.events);self.assertNotIn('rrde',self.w.state.results);self.assertNotIn('rrde_plot.csv',self.w.state.exports)

    def test_publish_failure_keeps_draft_and_original_file(self):
        self.w.stage_config_updates('conditions',{self.ident:{'collection_efficiency':.4}})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'existing.orrproj';path.write_bytes(b'original')
            with patch('application.tasks.os.replace',side_effect=PermissionError('read-only target')):
                self.win.start_task('project',{'target':str(path)});self.wait()
            self.assertEqual(path.read_bytes(),b'original');self.assertTrue(self.w.has_draft())
            self.assertEqual(self.w.state.configs[self.ident]['collection_efficiency'],.369)
            self.assertTrue(any(isinstance(e,tuple) and e[0]=='failed' for e in self.events))

    def test_close_cancel_preserves_applied_but_unsaved_project(self):
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QMessageBox
        self.win.force_close=False;self.assertTrue(self.win.has_unsaved_work());self.assertFalse(self.w.has_draft())
        event=QCloseEvent()
        with patch('desktop.lifecycle.QMessageBox.question',return_value=QMessageBox.StandardButton.Cancel):self.win.closeEvent(event)
        self.assertFalse(event.isAccepted());self.assertEqual(len(self.w.state.traces),10)

    def test_project_save_preserves_uncomputed_valid_inputs_and_marks_clean(self):
        from orr_core import unpack_project
        pane=self.win.analyses['kl'];pane.scheme.setCurrentIndex(pane.scheme.findData('custom'));pane.constants['C'].setText('2.4e-6')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'inputs.orrproj';self.win.save_project(path)
            settings=unpack_project(path.read_bytes())[2]
            self.assertEqual(settings['kl']['C'],2.4e-6);self.assertFalse(self.win.has_unsaved_work())
            self.assertNotIn('kl',self.w.state.results)

    def test_invalid_uncomputed_input_blocks_save_without_overwriting(self):
        pane=self.win.analyses['kl'];pane.scheme.setCurrentIndex(pane.scheme.findData('custom'));pane.constants['C'].setText('wrong')
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'keep.orrproj';path.write_bytes(b'original')
            with self.assertRaises(ValueError):self.win.save_project(path)
            self.assertEqual(path.read_bytes(),b'original');self.assertEqual(pane.constants['C'].text(),'wrong')

    def test_background_coverage_updates_inputs_without_fitting(self):
        pane=self.win.analyses['kl'];pane.request_coverage();self.wait()
        self.assertLess(float(pane.start.text()),float(pane.end.text()))
        self.assertNotIn('kl',self.w.state.results);self.assertNotIn('kl_plot.csv',self.w.state.exports)

    def test_close_during_job_defers_window_destruction_until_cancelled(self):
        from PySide6.QtGui import QCloseEvent
        self.win.show();self.app.processEvents();self.win.jobs.start('parameters',{},executor=delayed)
        event=QCloseEvent();self.win.closeEvent(event);self.assertFalse(event.isAccepted());self.assertTrue(self.win.jobs.busy)
        self.wait();self.app.processEvents();self.assertFalse(self.win.isVisible())

    def test_save_failure_during_close_keeps_window_and_inputs(self):
        from PySide6.QtGui import QCloseEvent
        from PySide6.QtWidgets import QMessageBox
        self.win.force_close=False;self.win.show();self.app.processEvents()
        self.w.stage_config_updates('conditions',{self.ident:{'collection_efficiency':.4}})
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'keep.orrproj';path.write_bytes(b'original')
            with patch('desktop.lifecycle.QMessageBox.question',return_value=QMessageBox.StandardButton.Save),patch('desktop.lifecycle.QFileDialog.getSaveFileName',return_value=(str(path),'')),patch('application.tasks.os.replace',side_effect=PermissionError('blocked')):
                event=QCloseEvent();self.win.closeEvent(event);self.assertFalse(event.isAccepted());self.wait()
            self.assertTrue(self.win.isVisible());self.assertTrue(self.w.has_draft())
            self.assertEqual(path.read_bytes(),b'original');self.assertEqual(self.w.state.configs[self.ident]['collection_efficiency'],.369)

    def test_cancel_after_temp_is_ready_still_prevents_final_publication(self):
        import threading
        from PySide6.QtCore import QTimer
        from application.tasks import execute
        ready=threading.Event();release=threading.Event()
        def held(job,cancelled,progress):
            result=execute(job,cancelled,progress);ready.set()
            while not release.wait(.005):pass
            return result
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'keep.json';path.write_bytes(b'original')
            timer=QTimer();timer.setInterval(2)
            def late_cancel():
                if ready.is_set():self.win.jobs.cancel();release.set();timer.stop()
            timer.timeout.connect(late_cancel);timer.start()
            try:
                self.win.jobs.start('parameters',{'target':str(path)},executor=held);self.wait()
            finally:release.set();timer.stop()
            self.assertEqual(path.read_bytes(),b'original');self.assertIn('discarded',self.events)
            self.assertEqual(list(Path(directory).glob('.orr-worker-*')),[])
