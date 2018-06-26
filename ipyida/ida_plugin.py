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
