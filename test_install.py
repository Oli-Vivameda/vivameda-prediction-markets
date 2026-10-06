import subprocess, unittest
from unittest.mock import patch
import install

class FirstInstallation(unittest.TestCase):
    def test_absent_unit_not_stopped(self):
        with patch.object(install,'command',return_value=subprocess.CompletedProcess([],0,stdout='not-found\n')) as cmd:
            self.assertFalse(install.stop_existing('vivameda-prediction-scanner.timer'))
            self.assertEqual(cmd.call_count,1)
    def test_existing_unit_stop_required(self):
        with patch.object(install,'command',side_effect=[subprocess.CompletedProcess([],0,stdout='loaded\n'),subprocess.CompletedProcess([],0)]) as cmd:
            self.assertTrue(install.stop_existing('vivameda-prediction-scanner.timer'))
            self.assertEqual(cmd.call_count,2)
    def test_stop_failure_not_ignored(self):
        with patch.object(install,'command',side_effect=[subprocess.CompletedProcess([],0,stdout='loaded\n'),subprocess.CalledProcessError(1,[]) ]):
            with self.assertRaises(subprocess.CalledProcessError):install.stop_existing('vivameda-prediction-scanner.timer')
    def test_unknown_load_state_refused(self):
        with patch.object(install,'command',return_value=subprocess.CompletedProcess([],0,stdout='')):
            with self.assertRaises(RuntimeError):install.stop_existing('vivameda-prediction-scanner.timer')
if __name__=='__main__':unittest.main()
