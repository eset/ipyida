# -*- encoding: utf8 -*-
#
# This module implements the recipe to launch a Jupyter Notebook from IDA and
# connect to it.
# See README.adoc for more details.
#
# Copyright (c) 2022 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

import sys
import os
import shutil
import subprocess
import time
import json
import threading
import webbrowser
import urllib.request
import urllib.error

import idaapi
import nbformat
import psutil
from jupyter_client import find_connection_file
from jupyter_core.paths import jupyter_data_dir


def _notebook_major_version():
    try:
        import notebook
    except ImportError:
        return None
    try:
        return int(notebook.__version__.split('.')[0])
    except (AttributeError, ValueError):
        return None


def _list_running_servers():
    """Return an iterator over running notebook/jupyter servers.

    notebook 7 dropped ``notebook.notebookapp`` and runs on top of
    ``jupyter_server``; notebook 6 still exposes its own server list.
    """
    major = _notebook_major_version()
    if major is not None and major >= 7:
        from jupyter_server.serverapp import list_running_servers
    else:
        from notebook.notebookapp import list_running_servers
    return list_running_servers()


def _server_root_dir(server_info):
    """Return the root directory of a running server.

    notebook 6 reports ``notebook_dir``; jupyter_server (notebook 7) reports
    ``root_dir``.
    """
    return server_info.get("root_dir") or server_info.get("notebook_dir") or ""

def _python_executable():
    # sys.executable in IDA is ida{q,t}{.exe,}, not a Python interpreter.
    # Locate the real Python that backs this environment instead.
    if sys.platform == 'win32':
        # Virtualenvs put Python.exe in Scripts/; regular installs at sys.prefix.
        python = os.path.join(sys.prefix, 'Scripts', 'Python.exe')
        if not os.path.exists(python):
            python = os.path.join(sys.prefix, 'Python.exe')
    else:
        python = os.path.join(sys.prefix, 'bin', 'python')
        if sys.version_info.major >= 3:
            python += str(sys.version_info.major)
    return python


# --- Subprocess lifetime binding -------------------------------------------
#
# IDA's plugin term() is best-effort: if IDA crashes, is killed from Task
# Manager, or is shut down indirectly (e.g. the user clicks "Shutdown" in
# the notebook browser tab, which the proxy kernel forwards to IDA's
# embedded kernel), term() never runs and the notebook subprocess survives
# as an orphan -- still bound to port 8888 with stale runtime files in
# ``%JUPYTER_RUNTIME_DIR%``. The next IDA session can't reach its own
# kernel through that stale server.
#
# Bind the subprocess to IDA's process lifetime so the OS itself kills it
# when IDA goes away:
#   * Windows: a Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE. The
#     job handle is held by IDA; when IDA's handle table is torn down, the
#     last handle closes and the OS terminates every process in the job.
#   * Linux: prctl(PR_SET_PDEATHSIG, SIGTERM) in the child via preexec_fn.

if sys.platform == 'win32':
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
    _JobObjectExtendedLimitInformation = 9

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", _IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    ]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

    _ipyida_job_handle = None

    def _get_ipyida_job():
        global _ipyida_job_handle
        if _ipyida_job_handle is not None:
            return _ipyida_job_handle
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not _kernel32.SetInformationJobObject(
            job, _JobObjectExtendedLimitInformation,
            ctypes.byref(info), ctypes.sizeof(info),
        ):
            _kernel32.CloseHandle(job)
            return None
        _ipyida_job_handle = job
        return job

    def _bind_proc_to_ida_lifetime(proc):
        job = _get_ipyida_job()
        if job is None:
            return
        handle = getattr(proc, "_handle", None)
        if handle is None:
            return
        if not _kernel32.AssignProcessToJobObject(job, int(handle)):
            # Pre-Win8 a process can only belong to one job; if IDA is
            # already inside an outer job that forbids breakaway we can't
            # nest. Falling back to the term() path is still safe.
            err = ctypes.get_last_error()
            print("-> AssignProcessToJobObject failed (err=%d); "
                  "notebook will not be auto-killed on IDA crash" % err)

else:
    def _bind_proc_to_ida_lifetime(proc):
        # Lifetime binding on Linux is set up in the child via preexec_fn;
        # nothing to do in the parent after Popen.
        pass


def _child_set_pdeathsig():
    # Linux only: ask the kernel to send SIGTERM when the parent dies.
    if not sys.platform.startswith('linux'):
        return
    try:
        import ctypes
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        PR_SET_PDEATHSIG = 1
        SIGTERM = 15
        libc.prctl(PR_SET_PDEATHSIG, SIGTERM, 0, 0, 0)
    except Exception:
        pass


def _popen_python_module(module, *args, **kwargs):
    python = _python_executable()
    if sys.platform == 'win32':
        si_hidden_window = subprocess.STARTUPINFO()
        si_hidden_window.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si_hidden_window.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = si_hidden_window
    elif sys.platform.startswith('linux'):
        kwargs.setdefault("preexec_fn", _child_set_pdeathsig)
    proc = subprocess.Popen([ python, "-m", module ] + list(args), **kwargs)
    _bind_proc_to_ida_lifetime(proc)
    return proc


class NotebookManager(object):

    def __init__(self, connection_file):
        self.connection_file = connection_file
        self.nb_proc = None
        self.nb_pipe_thread = None
        self.nb_pipe_buffer = []
        self.nb_pipe_lock = threading.Lock()

    @staticmethod
    def ensure_kernel_proxy_installed():
        try:
            import jupyter_kernel_proxy
        except ImportError:
            print("-> Installing jupyter-kernel-proxy...")
            return _popen_python_module(
                "pip", "install", "jupyter-kernel-proxy"
            ).wait() == 0
        else:
            return True

    def _kernelspec_name(self):
        # One kernelspec per IDA process so concurrent IDAs don't fight
        # over a single shared spec (each spec pins its proxy to a
        # different IDA via env.IPYIDA_KERNEL_FILE).
        return "ipyida-%d" % os.getpid()

    @staticmethod
    def _cleanup_stale_kernelspecs():
        # Remove ipyida-<pid> kernelspec directories whose IDA process
        # is no longer running -- otherwise crashed/force-killed IDAs
        # leave entries cluttering JupyterLab's Launcher forever.
        kernels_dir = os.path.join(jupyter_data_dir(), "kernels")
        if not os.path.isdir(kernels_dir):
            return
        prefix = "ipyida-"
        for name in os.listdir(kernels_dir):
            if not name.startswith(prefix):
                continue
            try:
                pid = int(name[len(prefix):])
            except ValueError:
                continue
            if pid == os.getpid():
                continue
            if psutil.pid_exists(pid):
                continue
            shutil.rmtree(os.path.join(kernels_dir, name), ignore_errors=True)

    def ensure_kernelspec_installed(self):
        """Install (or refresh) this IDA instance's own proxy kernelspec.

        Each IDA writes ``<data_dir>/kernels/ipyida-<pid>/kernel.json``
        with:
          - argv: our ``ipyida.proxy_runner`` wrapper, plus IDA's
            connection-file basename as the second positional arg.
            proxy_runner uses it to dial the right kernel directly,
            instead of guessing by ``kernel-*.json`` atime (which breaks
            after a few open/shutdown cycles).
          - metadata.debugger=true so JupyterLab / Notebook 7 enable the
            debug toolbar button.
        """
        # jupyter_kernel_proxy itself must be importable; proxy_runner
        # wraps it. We do not call its ``install`` -- we install our
        # own per-IDA spec rather than mutating the shared "proxy" one.
        try:
            import jupyter_kernel_proxy  # noqa: F401
        except ImportError:
            return False

        self._cleanup_stale_kernelspecs()

        spec_dir = os.path.join(
            jupyter_data_dir(), "kernels", self._kernelspec_name()
        )
        spec_path = os.path.join(spec_dir, "kernel.json")
        spec = {
            "argv": [
                _python_executable(),
                "-m", "ipyida.proxy_runner",
                "{connection_file}",
                os.path.basename(self.connection_file),
            ],
            "display_name": "IDA Pro (PID %d)" % os.getpid(),
            "language": "python",
            "metadata": {"debugger": True},
        }
        try:
            os.makedirs(spec_dir, exist_ok=True)
            with open(spec_path, "w") as f:
                json.dump(spec, f)
        except OSError as e:
            print("-> Could not write ipyida kernelspec: %s" % e)
            return False
        return True

    @staticmethod
    def ensure_notebook_installed():
        try:
            import notebook
        except ImportError:
            print("-> Installing jupyter-notebook...")
            return _popen_python_module(
                "pip", "install", "notebook"
            ).wait() == 0
        else:
            return True

    def _get_running_notebook_config(self):
        idb_path = idaapi.get_path(idaapi.PATH_TYPE_IDB)
        for server_info in _list_running_servers():
            root = _server_root_dir(server_info)
            if root and idb_path.startswith(root):
                return server_info
        return None

    def _create_proxy_session(self, server_info, relative_path):
        """Pre-create a kernel session bound to this IDA's proxy kernel.

        Needed on notebook 7 because its JupyterLab-based frontend does not
        honour the legacy ``?kernel_name=`` query string the way notebook 6
        did. Posting the session beforehand makes the page reuse the
        already-attached proxy kernel when it opens. Harmless on notebook 6
        (the existing session is reused instead of creating a duplicate).
        """
        base = server_info.get("url", "").rstrip("/")
        token = server_info.get("token", "")
        if not base:
            return
        body = json.dumps({
            "path": "/".join(relative_path.split(os.path.sep)),
            "type": "notebook",
            "name": "",
            "kernel": {"name": self._kernelspec_name()},
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "token " + token
        req = urllib.request.Request(
            base + "/api/sessions", data=body, headers=headers, method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10).read()
        except (urllib.error.URLError, OSError) as e:
            # Non-fatal: fall back to the URL-query selection path.
            print("-> Could not pre-create proxy session: %s" % e)

    def _parse_args(self, line):
        args = line.split()
        parsed = dict()
        if "--skip-dependency-checks" in args:
            parsed["skip_dependency_checks"] = True
            args.remove("--skip-dependency-checks")
        if len(args) > 0:
            parsed["filename"] = args[0]
        return parsed

    def open_notebook(self, line):
        """
        Open a Jupyter Notebook in the same directory where the currently open
        .idb (or .i64) is located. Unless specified, the notebook file (.ipynb)
        will have the same name as the IDA database file.

        The following arguments can be used:

            --skip-dependency-checks    Assumes Notebook and jupyter-kernel-proxy
                                        are already installed
            <filename>                  Filename of the notebook to open.
                                        (.ipynb may be omitted)
        """

        idb_path = idaapi.get_path(idaapi.PATH_TYPE_IDB)
        if len(idb_path) == 0:
            raise Exception("No file currently open")

        args = self._parse_args(line)

        if not args.get("skip_dependency_checks", False):
            if not self.ensure_notebook_installed() or \
               not self.ensure_kernel_proxy_installed() or \
               not self.ensure_kernelspec_installed():
                raise Exception("Could not find or install all requirements")

        nb_server_info = self._get_running_notebook_config()

        if nb_server_info is None:
            print("-> Starting notebook")
            # Use ``python -m notebook`` instead of ``python -m jupyter notebook``
            # to bypass jupyter_core's dispatch to the ``jupyter-notebook`` script
            # on PATH -- pip downgrades between notebook 7 and 6 can leave that
            # script pointing at the wrong module (e.g. 7's ``notebook.app``
            # after a downgrade to 6). ``notebook/__main__.py`` exists in both
            # 6 and 7 and routes to the right entry point.
            self.nb_proc = _popen_python_module(
                "notebook", "--no-browser", "-y",
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True
            )
            try_count = 0
            while nb_server_info is None and self.nb_proc.poll() is None and try_count < 10:
                time.sleep(0.5)
                nb_server_info = self._get_running_notebook_config()
                try_count += 1
            if nb_server_info is None:
                self.nb_proc.terminate()
                print(self.nb_proc.stdout.read())
                raise Exception("Couldn't start Jupyter Notebook")
            else:
                self.nb_pipe_thread = threading.Thread(target=self._notebook_stdout_thread)
                self.nb_pipe_thread.start()

        ipynb_filename = args.get("filename", os.path.basename(idb_path).rsplit(".", 1)[0])
        if not ipynb_filename.endswith(".ipynb"):
            ipynb_filename += ".ipynb"
        ipynb_path = os.path.join(os.path.dirname(idb_path), ipynb_filename)
        if not os.path.exists(ipynb_path):
            # Create the file, the notebook won't do it for us
            with open(ipynb_path, "w") as f:
                nb = nbformat.versions[nbformat.current_nbformat].new_notebook()
                json.dump(nb, f)
        relative_path = os.path.relpath(ipynb_path, _server_root_dir(nb_server_info))
        # Fallback ordering for jupyter_kernel_proxy: it picks the
        # kernel-*.json with the newest st_atime. ``open(..., "r")`` does
        # NOT update atime on NTFS volumes where LastAccessUpdate is
        # disabled (the default on most Windows 10/11 boxes). Use
        # ``os.utime`` which sets the timestamp directly via SetFileTime
        # and isn't affected by that setting. (Primary selection happens
        # via IPYIDA_KERNEL_FILE in the kernelspec env; this is only a
        # safety net.)
        try:
            os.utime(find_connection_file(self.connection_file), None)
        except OSError:
            pass
        # On notebook 7 the JupyterLab-based frontend ignores the
        # ?kernel_name= query argument. Posting a session in advance attaches
        # the proxy kernel so the notebook page picks it up on load.
        self._create_proxy_session(nb_server_info, relative_path)
        url = nb_server_info.get("url") + \
            "notebooks/" + "/".join(relative_path.split(os.path.sep)) + \
            '?kernel_name=' + self._kernelspec_name() + \
            '&token=' + nb_server_info.get("token")
        webbrowser.open(url)
        return url

    def _notebook_stdout_thread(self):
        while self.nb_proc.poll() is None:
            r = self.nb_proc.stdout.readline()
            with self.nb_pipe_lock:
                self.nb_pipe_buffer.append(r)

    def notebook_log(self, line):
        "Print output from Jupyter Notebook started by IPyIDA"
        if self.nb_proc:
            with self.nb_pipe_lock:
                for s in self.nb_pipe_buffer:
                    print(s, end="")
                self.nb_pipe_buffer = []
        else:
            print("Notebook isn't running or managed by this IPyIDA instance")

    @property
    def magic_functions(self):
        return [self.open_notebook, self.notebook_log]

    def _shutdown_server_via_api(self, timeout=3):
        """POST ``/api/shutdown`` so the server cleans up its runtime files.

        ``Popen.terminate()`` on Windows is ``TerminateProcess`` (unconditional
        kill), which leaves the per-server token/secret files behind in
        ``%JUPYTER_RUNTIME_DIR%`` and confuses ``list_running_servers()`` on
        the next launch. Asking the server to shut itself down lets it unlink
        those files. Returns True on a successful HTTP response, False if we
        should fall back to ``terminate()``.
        """
        if self.nb_proc is None:
            return False
        server_info = None
        try:
            for info in _list_running_servers():
                if info.get("pid") == self.nb_proc.pid:
                    server_info = info
                    break
        except Exception:
            return False
        if server_info is None:
            return False
        base = server_info.get("url", "").rstrip("/")
        if not base:
            return False
        token = server_info.get("token", "")
        headers = {}
        if token:
            headers["Authorization"] = "token " + token
        req = urllib.request.Request(
            base + "/api/shutdown", data=b"", headers=headers, method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=timeout)
        except (urllib.error.URLError, OSError):
            return False
        return True

    def shutdown(self):
        if self.nb_proc:
            graceful = False
            try:
                graceful = self._shutdown_server_via_api(timeout=3)
            except Exception:
                graceful = False
            if graceful:
                try:
                    self.nb_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    graceful = False
            if not graceful:
                try:
                    self.nb_proc.terminate()
                except Exception:
                    pass
        if self.nb_pipe_thread:
            self.nb_pipe_thread.join(timeout=2)
        # Drop our own per-IDA kernelspec so dead specs don't accumulate.
        # (Crashed IDAs leave theirs behind; ensure_kernelspec_installed
        # in the next IDA cleans those up.)
        spec_dir = os.path.join(
            jupyter_data_dir(), "kernels", self._kernelspec_name()
        )
        shutil.rmtree(spec_dir, ignore_errors=True)
