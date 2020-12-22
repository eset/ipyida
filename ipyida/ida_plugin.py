# -*- encoding: utf8 -*-
#
# IDA plugin definition.
#
# Copyright (c) 2015-2018 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

import idaapi
from ipyida import ida_qtconsole, kernel

class IPyIDAPlugIn(idaapi.plugin_t):
    wanted_name = "IPyIDA"
    wanted_hotkey = "Shift-."
    flags = 0
    comment = ""
    help = "Starts an IPython qtconsole in IDA Pro"
    
    def init(self):
        global _kernel
        self.kernel = _kernel
        self.widget = None
        monkey_patch_IDAPython_ExecScript()
        return idaapi.PLUGIN_KEEP

    def run(self, args):
        if not self.kernel.started:
            self.kernel.start()
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
    from PyQt5.QtWidgets import QApplication
    import qasync
    import asyncio
    if isinstance(asyncio.get_event_loop(), qasync.QEventLoop):
        print("Note: qasync event loop already set up.")
    else:
        qapp = QApplication.instance()
        loop = qasync.QEventLoop(qapp, already_running=True)
        asyncio.set_event_loop(loop)

if ida_qtconsole.is_using_pyqt5() and kernel.is_using_ipykernel_5():
    _setup_asyncio_event_loop()

_kernel = kernel.IPythonKernel()
_kernel.start()

def _do_load():
    ipyida_plugin_path = __file__
    if ipyida_plugin_path.endswith("pyc"):
        # IDA Python can't load pyc, only the Python source so we remove the "c"
        ipyida_plugin_path = ipyida_plugin_path[:-1]
    idaapi.load_plugin(ipyida_plugin_path)

def load():
    """
    Perform necessary steps to load the plugin inside IDA. If no IDB is open, it
    will wait until it is open to load it.
    """
    if idaapi.get_root_filename() is None:
        # No idb open yet
        def handler(event, old=0):
            if event == idaapi.NW_OPENIDB:
                _do_load()
            elif event == idaapi.NW_TERMIDA:
                idaapi.notify_when(idaapi.NW_TERMIDA | idaapi.NW_OPENIDB | idaapi.NW_REMOVE, handler)
        def _install():
            idaapi.notify_when(idaapi.NW_TERMIDA | idaapi.NW_OPENIDB, handler)
            # return -1 to remove the timer
            return -1
        # It's possible we can't use the notify_when API call yet when IDA opens
        # so try register a timer to add the event listner in the proper "state"
        idaapi.register_timer(1, _install)
    else:
        # IDA is fully loaded and an idb is open, just load the plugin.
        _do_load()

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
