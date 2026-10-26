"""Actual Qt widgets; skipped only in environments without desktop dependencies."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
QT=importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(QT,'Install requirements/desktop.txt for native widget checks')
class DesktopMinimumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])

    def setUp(self):
        from desktop.window import MainWindow
        self.window=MainWindow();self.window.force_close=True
        self.addCleanup(self.window.close)

    def test_native_closed_loop_with_unicode_paths(self):
        from desktop.smoke import verify
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(verify(self.window,Path(directory))['passed'])

    def test_failed_candidate_cannot_export_previous_curve(self):
        from migration_fixtures import workspace
        from application.workspace import Workspace,State
        from application.curves import calculate_curves
        from orr_core import DataError
        traces,configs,settings=workspace();w=Workspace(State(traces=traces,configs=configs,settings=settings))
        ident=next(iter(traces));calculate_curves(w,[ident]);self.assertIn('polarization.png',w.state.exports)
        w.stage_config_updates('conditions',{ident:{'pH':None}})
        with self.assertRaises(DataError):calculate_curves(w,[ident])
        self.assertNotIn('polarization.png',w.state.exports)
        self.assertTrue(w.has_draft());self.assertEqual(w.state.configs[ident]['pH'],13)
