# -*- encoding: utf8 -*-
#
# This module allows an IPython to be embeded inside IDA.
# You need the IPython module to be accessible from IDA for this to work.
# See README.adoc for more details.
#
# Copyright (c) 2015 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

from PySide import QtCore

from IPython.kernel.zmq.kernelapp import IPKernelApp
import IPython.utils.frame
import IPython.kernel.zmq.iostream

import sys

_ida_ipython_qtimer = None

# The IPython kernel will override sys.std{out,err}. We keep a copy to let the
# existing embeded IDA console continue working, and also let IPython output to
# it.
_ida_stdout = sys.stdout
_ida_stderr = sys.stderr

# IPython will override sys.excepthook and send exception to sys.__stderr__. IDA
# expect exception to be written to sys.stderr (overridden by IDA) to print them
# in the console window. Used by wrap_excepthook.
_ida_excepthook = sys.excepthook

class IDATeeOutStream(IPython.kernel.zmq.iostream.OutStream):

    def write(self, string):
        "Write on both the previously saved IDA std output and zmq's stream"
        if self.name == "stdout" and _ida_stdout:
            _ida_stdout.write(string)
        elif self.name == "stderr" and _ida_stderr:
            _ida_stderr.write(string)
        super(self.__class__, self).write(string)

def wrap_excepthook(ipython_excepthook):
    """
    Return a function that will call both the ipython kernel execepthook
    and IDA's
    """
    def ipyida_excepthook(*args):
        _ida_excepthook(*args)
        ipython_excepthook(*args)
    return ipyida_excepthook

class IPythonKernel(object):
    def __init__(self):
        self._ida_ipython_qtimer = None
        self.connection_file = None
    
    def start(self):
        if self._ida_ipython_qtimer is not None:
            raise Exception("IPython kernel is already running.")

        # The IPKernelApp initialization is based on the IPython source for
        # IPython.embed_kernel available here:
        # https://github.com/ipython/ipython/blob/rel-3.2.1/IPython/kernel/zmq/embed.py

        if IPKernelApp.initialized():
            app = IPKernelApp.instance()
        else:
            app = IPKernelApp.instance(
                outstream_class='ipyida.kernel.IDATeeOutStream'
            )
            app.initialize()

            main = app.kernel.shell._orig_sys_modules_main_mod
            if main is not None:
                sys.modules[app.kernel.shell._orig_sys_modules_main_name] = main
        
            # IPython <= 3.2.1 will send exception to sys.__stderr__ instead of
            # sys.stderr. IDA's console will not be able to display exceptions if we
            # don't send it to IDA's sys.stderr. To fix this, we call both the
            # ipython's and IDA's excepthook (IDA's excepthook is actually Python's
            # default).
            sys.excepthook = wrap_excepthook(sys.excepthook)

        # Load the calling scope
        (ida_module, ida_locals) = IPython.utils.frame.extract_module_locals(1)

        if 'idaapi' not in ida_locals:
            raise Exception("{0:s} must be called from idapythonrc.py or "
                            "IDA's prompt.".format("IPythonKernel.start"))

        app.kernel.user_module = ida_module
        app.kernel.user_ns = ida_locals

        app.shell.set_completer_frame()

        app.kernel.start()
        app.kernel.do_one_iteration()
    
        self.connection_file = app.connection_file

        # Schedule the IPython kernel to run on the Qt main loop with a QTimer
        qtimer = QtCore.QTimer()

        # Use _poll_interval as docuementented here:
        # https://ipython.org/ipython-doc/dev/config/eventloops.html
        qtimer.setInterval(int(1000 * app.kernel._poll_interval))
        qtimer.timeout.connect(app.kernel.do_one_iteration)

        qtimer.start()

        # We keep tht qtimer in a global variable to this module to allow to
        # manually stop the kernel later with stop_ipython_kernel.
        # There's a second purpose: If there is no more reference to the QTimer,
        # it will get garbage collected and the timer will stop calling
        # kernel.do_one_iteration. Keep this in mind before removing this line.
        self._ida_ipython_qtimer = qtimer

    def stop(self):
        if self._ida_ipython_qtimer is not None:
            self._ida_ipython_qtimer.stop()
        self._ida_ipython_qtimer = None
        self.connection_file = None
        sys.stdout = _ida_stdout
        sys.stderr = _ida_stderr

    @property
    def started(self):
        return self._ida_ipython_qtimer is not None
