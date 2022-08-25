# -*- encoding: utf8 -*-
#
# IDA plugin definition.
#
# Copyright (c) 2015-2018 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

import idaapi
from ipyida import ida_qtconsole, kernel
from PyQt5.QtWidgets import QApplication

class IPyIDAPlugIn(idaapi.plugin_t):
    wanted_name = "IPyIDA"
    wanted_hotkey = "Shift-."
    flags = idaapi.PLUGIN_FIX
    comment = ""
    help = "Starts an IPython qtconsole in IDA Pro"
    
    def init(self):
        self.kernel = kernel.IPythonKernel()
        self.kernel.start()
        self.widget = None
        monkey_patch_IDAPython_ExecScript()
        return idaapi.PLUGIN_KEEP

    def run(self, args):
        if self.widget is None:
            self.widget = ida_qtconsole.IPythonConsole(self.kernel.connection_file)
        self.widget.Show()

    def term(self):
        if self.widget:
            self.widget.Close(0)
            self.widget = None
        if self.kernel:
            self.kernel.stop()


def PLUGIN_ENTRY():
    return IPyIDAPlugIn()

# Links Qt's event loop with asyncio's event loop. This allows asyncio to
# work properly, which is required for ipykernel >= 5 (more specifically,
# because ipykernel uses tornado, which is backed by asyncio).
def _setup_asyncio_event_loop():
    import qasync
    import asyncio
    if isinstance(asyncio.get_event_loop(), qasync.QEventLoop):
        print("Note: qasync event loop already set up.")
    else:
        qapp = QApplication.instance()
        loop = qasync.QEventLoop(qapp, already_running=True)
        asyncio.set_event_loop(loop)

if QApplication.instance() and ida_qtconsole.is_using_pyqt5() and kernel.is_using_ipykernel_5():
    _setup_asyncio_event_loop()

def monkey_patch_IDAPython_ExecScript():
    """
    This funtion wraps IDAPython_ExecScript to avoid having an empty string has
    a __file__ attribute of a module.
    See https://github.com/idapython/src/pull/23
    """
    # Test the behavior IDAPython_ExecScript see if it needs patching
    import sys, os
    fake_globals = {}
    if idaapi.IDA_SDK_VERSION < 700:
        idaapi.IDAPython_ExecScript(os.devnull, fake_globals)
    else:
        idaapi.IDAPython_ExecScript(os.devnull, fake_globals, False)
    if "__file__" in fake_globals:
        # Monkey patch IDAPython_ExecScript
        original_IDAPython_ExecScript = idaapi.IDAPython_ExecScript
        def IDAPython_ExecScript_wrap(script, g, print_error=True):
            has_file = "__file__" in g
            try:
                if idaapi.IDA_SDK_VERSION < 700:
                    original_IDAPython_ExecScript(script, g)
                else:
                    original_IDAPython_ExecScript(script, g, print_error)
            finally:
                if not has_file and "__file__" in g:
                    del g["__file__"]
        idaapi.IDAPython_ExecScript = IDAPython_ExecScript_wrap
        try:
            # Remove the empty strings on existing modules
            for mod_name in sys.modules:
                if hasattr(sys.modules[mod_name], "__file__") and \
                   bool(sys.modules[mod_name].__file__) is False:
                    del sys.modules[mod_name].__file__
        except RuntimeError:
            # Best effort here, let's not crash if something goes wrong
            pass
