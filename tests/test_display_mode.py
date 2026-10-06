import importlib.machinery
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

HELPER = Path(__file__).resolve().parents[1] / "ac-power-profile"
loader = importlib.machinery.SourceFileLoader("display_mode", str(HELPER))
spec = importlib.util.spec_from_loader(loader.name, loader)
module = importlib.util.module_from_spec(spec)
loader.exec_module(module)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(self.root), "XDG_STATE_HOME": str(self.root / "state")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.worker = module.Worker()

    def test_auto_follows_power_and_manual_override_survives_restart(self):
        with patch.object(module, "session_signature", return_value="session"), patch.object(module, "ac_online", return_value=True) as power, patch.object(module.shutil, "which", return_value="monique"), patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            self.worker.apply()
            self.assertEqual(run.call_args.args[0][-1], "Builtin")
            self.worker.apply()
            self.assertEqual(run.call_count, 1)
            power.return_value = False
            self.worker.apply()
            self.assertEqual(run.call_args.args[0][-1], "Builtin 60hz")
            self.worker.select_mode("120hz")
            self.worker.apply()
            self.assertEqual(run.call_args.args[0][-1], "Builtin")
            restarted = module.Worker()
            self.assertEqual(restarted.mode, "120hz")
            restarted.apply()
            self.assertEqual(run.call_args.args[0][-1], "Builtin")
            restarted.select_mode("auto")
            restarted.apply()
            self.assertEqual(run.call_args.args[0][-1], "Builtin 60hz")

    def test_wait_for_session_retry_failure_and_reapply_after_relogin(self):
        with patch.object(module, "session_signature", return_value=None) as session, patch.object(module, "ac_online", return_value=False), patch.object(module.shutil, "which", return_value="monique"), patch.object(module.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)) as run, patch.object(module.time, "monotonic", return_value=0) as clock:
            self.worker.apply()
            run.assert_not_called()
            session.return_value = "first-session"
            self.worker.apply()
            self.assertIsNone(self.worker.last_applied)
            self.worker.apply()
            self.assertEqual(run.call_count, 1)
            clock.return_value = module.RETRY_INTERVAL
            run.return_value.returncode = 0
            self.worker.apply()
            self.assertEqual(run.call_count, 2)
            session.return_value = None
            self.worker.apply()
            session.return_value = "second-session"
            self.worker.apply()
            self.assertEqual(run.call_args.kwargs["env"]["HYPRLAND_INSTANCE_SIGNATURE"], "second-session")
            self.assertEqual(run.call_count, 3)

    def test_legacy_state_migration_and_invalid_state(self):
        (self.root / "end4-display-mode").write_text("Builtin 60hz\n")
        self.assertEqual(module.Worker().mode, "60hz")
        (self.root / "end4-display-mode").write_text("invalid\n")
        self.assertEqual(module.Worker().mode, "auto")

    def test_ac_supply_reading(self):
        supply = self.root / "supplies/AC"
        supply.mkdir(parents=True)
        supply.joinpath("type").write_text("Mains\n")
        supply.joinpath("online").write_text("1\n")
        real_path = Path
        with patch.object(module, "Path", side_effect=lambda value: self.root / "supplies" if value == "/sys/class/power_supply" else real_path(value)):
            self.assertTrue(module.ac_online())
            supply.joinpath("online").write_text("0\n")
            self.assertFalse(module.ac_online())
            supply.joinpath("online").unlink()
            self.assertFalse(module.ac_online())


class SocketTests(unittest.TestCase):
    def test_activation_protocol_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            sock = root / "end4-display-mode.sock"
            state = root / "state/end4/display-mode"
            env = os.environ.copy()
            env.update(XDG_RUNTIME_DIR=str(root), XDG_STATE_HOME=str(root / "state"))
            # No Hyprland socket exists: the worker must still accept requests.
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(sock))
                listener.listen()
                wrapper = '''import os, sys
fd = int(sys.argv[1])
if fd != 3:
    os.dup2(fd, 3)
os.set_inheritable(3, True)
os.environ['LISTEN_PID'] = str(os.getpid())
os.environ['LISTEN_FDS'] = '1'
os.execv(sys.executable, [sys.executable, sys.argv[2], '--serve'])
'''
                process = subprocess.Popen(["python3", "-c", wrapper, str(listener.fileno()), str(HELPER)], env=env, pass_fds=(listener.fileno(),), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    with socket.socket(socket.AF_UNIX) as slow:
                        slow.connect(str(sock))
                        slow.sendall(b"au")
                        result = subprocess.run([str(HELPER), "--set-mode", "120hz"], env=env, timeout=5, capture_output=True)
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(state.read_text(), "120hz\n")
                        slow.sendall(b"to\n")
                        slow.settimeout(5)
                        self.assertEqual(slow.recv(128), b"ok\n")
                    with socket.socket(socket.AF_UNIX) as invalid:
                        invalid.connect(str(sock))
                        invalid.sendall(b"garbage\n")
                        invalid.settimeout(5)
                        self.assertTrue(invalid.recv(128).startswith(b"error:"))
                    self.assertEqual(state.read_text(), "auto\n")
                    self.assertIsNone(process.poll())
                finally:
                    process.terminate()
                    process.communicate(timeout=5)

    def test_discovers_session_without_environment_and_skips_stale_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            live = root / "hypr/live/.socket.sock"
            stale = root / "hypr/stale/.socket.sock"
            live.parent.mkdir(parents=True)
            stale.parent.mkdir(parents=True)
            with socket.socket(socket.AF_UNIX) as dead:
                dead.bind(str(stale))
            with socket.socket(socket.AF_UNIX) as listener:
                listener.bind(str(live))
                listener.listen()
                with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(root), "HYPRLAND_INSTANCE_SIGNATURE": "stale"}):
                    self.assertEqual(module.session_signature(), "live")


if __name__ == "__main__":
    unittest.main()
