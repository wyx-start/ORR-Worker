"""Frozen launcher identity and ownership do not depend on an external python.exe."""
from pathlib import Path
import tempfile
import json
import unittest
from unittest.mock import patch

from browser_runtime import BrowserService,identity


class BrowserRuntimeTests(unittest.TestCase):
    def test_unrelated_pid_is_never_stopped(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=BrowserService(directory)
            manager.path.write_text(json.dumps({"key":"other","pid":123,"stamp":1}))
            with patch.object(manager,"read",return_value={"key":"other","pid":123,"stamp":1}),patch("browser_runtime.subprocess.run") as kill:
                manager.stop();kill.assert_not_called()
            self.assertTrue(manager.path.exists())

    def test_state_directory_is_independent_from_resources(self):
        with tempfile.TemporaryDirectory() as directory:
            manager=BrowserService(directory)
            self.assertNotEqual(manager.directory,manager.root)
            self.assertEqual(manager.key,identity(manager.root))


if __name__=="__main__":unittest.main()
