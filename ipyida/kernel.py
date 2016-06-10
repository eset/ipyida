# -*- encoding: utf8 -*-
#
# This module allows an IPython to be embeded inside IDA.
# You need the IPython module to be accessible from IDA for this to work.
# See README.adoc for more details.
#
# Copyright (c) 2015 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

from ipykernel.kernelapp import IPKernelApp
import IPython.utils.frame
import ipykernel.iostream

import sys
import os
import idaapi

# The IPython kernel will override sys.std{out,err}. We keep a copy to let the
# existing embeded IDA console continue working, and also let IPython output to
# it.
_ida_stdout = sys.stdout
_ida_stderr = sys.stderr

if sys.__stdout__.fileno() < 0:
    # IPython insist on using sys.__stdout__, however it's not available in IDA
    # on Windows. We'll replace __stdout__ to the "nul" to avoid exception when
    # writing and flushing on the bogus file descriptor.
    sys.__stdout__ = open(os.devnull, "w")

# IPython will override sys.excepthook and send exception to sys.__stderr__. IDA
# expect exception to be written to sys.stderr (overridden by IDA) to print them
# in the console window. Used by wrap_excepthook.
_ida_excepthook = sys.excepthook

class IDATeeOutStream(ipykernel.iostream.OutStream):

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
        self._timer = None
        self.connection_file = None
    
    def start(self):
        if self._timer is not None:
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
        
            # IPython <= 3.2.x will send exception to sys.__stderr__ instead of
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

        def ipython_kernel_iteration():
            app.kernel.do_one_iteration()
            return int(1000 * app.kernel._poll_interval)
        self._timer = idaapi.register_timer(int(1000 * app.kernel._poll_interval), ipython_kernel_iteration)

    def stop(self):
        if self._timer is not None:
            idaapi.unregister_timer(self._timer)
        self._timer = None
        self.connection_file = None
        sys.stdout = _ida_stdout
        sys.stderr = _ida_stderr

    @property
    def started(self):
        return self._timer is not None
