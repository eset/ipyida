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
import subprocess
import time
import json
import threading
import webbrowser
import urllib.request
import urllib.error

import idaapi
import nbformat
from jupyter_client.kernelspec import find_kernel_specs
from jupyter_client import find_connection_file


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


def _popen_python_module(module, *args, **kwargs):
    python = _python_executable()
    if sys.platform == 'win32':
        si_hidden_window = subprocess.STARTUPINFO()
        si_hidden_window.dwFlags = subprocess.STARTF_USESHOWWINDOW
        si_hidden_window.wShowWindow = subprocess.SW_HIDE
        kwargs["startupinfo"] = si_hidden_window
    return subprocess.Popen([ python, "-m", module ] + list(args), **kwargs)


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

    @staticmethod
    def ensure_kernelspec_installed():
        specs = find_kernel_specs()
        if "proxy" not in specs:
            print("-> Installing jupyter-kernel-proxy kernelspec...")
            if _popen_python_module("jupyter_kernel_proxy", "install").wait() != 0:
                return False
            specs = find_kernel_specs()
            if "proxy" not in specs:
                return False
        # Two patches on the kernelspec, idempotent:
        #   1. argv -> our proxy_runner wrapper, which suppresses the
        #      fallback kernel_info_reply that lacks fields like
        #      ``implementation: "ipython"``.
        #   2. metadata.debugger = true. JupyterLab / Notebook 7 enable the
        #      debug toolbar button purely from kernelspec metadata
        #      (see jupyterlab/packages/debugger/src/service.ts:isAvailable),
        #      not from kernel_info_reply. jupyter_kernel_proxy ships
        #      without it, so the button stays greyed out.
        spec_path = os.path.join(specs["proxy"], "kernel.json")
        try:
            with open(spec_path, "r") as f:
                spec = json.load(f)
            changed = False
            current_argv = spec.get("argv") or []
            desired_argv = (
                [current_argv[0] if current_argv else sys.executable]
                + ["-m", "ipyida.proxy_runner", "{connection_file}"]
            )
            if current_argv != desired_argv:
                spec["argv"] = desired_argv
                changed = True
            metadata = spec.setdefault("metadata", {})
            if not metadata.get("debugger"):
                metadata["debugger"] = True
                changed = True
            if changed:
                with open(spec_path, "w") as f:
                    json.dump(spec, f)
        except (OSError, ValueError) as e:
            print("-> Could not patch proxy kernelspec: %s" % e)
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

    @staticmethod
    def _create_proxy_session(server_info, relative_path):
        """Pre-create a kernel session bound to the proxy kernel.

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
            "kernel": {"name": "proxy"},
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
        # Update access time of the file so it's picked up by the proxy.
        # jupyter-kernel-proxy will use the file with the most recent access
        # time (like `jupyter console --existing`)
        with open(find_connection_file(self.connection_file), "r"): pass
        # On notebook 7 the JupyterLab-based frontend ignores the
        # ?kernel_name= query argument. Posting a session in advance attaches
        # the proxy kernel so the notebook page picks it up on load.
        self._create_proxy_session(nb_server_info, relative_path)
        url = nb_server_info.get("url") + \
            "notebooks/" + "/".join(relative_path.split(os.path.sep)) + \
            '?kernel_name=proxy&token=' + nb_server_info.get("token")
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

    def shutdown(self):
        if self.nb_proc:
            self.nb_proc.terminate()
        if self.nb_pipe_thread:
            self.nb_pipe_thread.join()
