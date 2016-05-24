# -*- encoding: utf8 -*-
#
# IDA plugin definition
#
# Copyright (c) 2015 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

import idaapi
from ipyida import qtconsole, kernel

class IPyIDAPlugIn(idaapi.plugin_t):
    wanted_name = "IPyIDA"
    wanted_hotkey = "Shift-."
    flags = 0
    comment = ""
    help = "TODO"
    
    def init(self):
        global _kernel
        self.kernel = _kernel
        self.widget = None
        return idaapi.PLUGIN_KEEP

    def run(self, args):
        if not self.kernel.started:
            self.kernel.start()
            self.widget = qtconsole.IPythonConsole(self.kernel.connection_file)
        if self.widget is None:
            self.widget = qtconsole.IPythonConsole(self.kernel.connection_file)
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

def load():
    ipyida_plugin_path = __file__
    if ipyida_plugin_path.endswith("pyc"):
        # IDA Python can't load pyc, only the Python source so we remove the "c"
        ipyida_plugin_path = ipyida_plugin_path[:-1]
    idaapi.load_plugin(ipyida_plugin_path)

def install():
    def handler(event, old=0):
        if event == idaapi.NW_OPENIDB:
            load()
        elif event == idaapi.NW_TERMIDA:
            idaapi.notify_when(idaapi.NW_TERMIDA | idaapi.NW_OPENIDB | idaapi.NW_REMOVE, handler)
    def _install():
        idaapi.notify_when(idaapi.NW_TERMIDA | idaapi.NW_OPENIDB, handler)
        return -1
    idaapi.register_timer(1000, _install)