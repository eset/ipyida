# -*- encoding: utf8 -*-
#
# This module integreate a qtconsole the the IDA GUI.
# See README.adoc for more details.
#
# Copyright (c) 2015 Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

from PySide import QtCore, QtGui
import idaapi
import sys
import ipyida.kernel

# QtSvg binairies are not bundled with IDA. So we monkey patch PySide to avoid
# IPython to load a module with missing binary files. This must happend before
# importing RichIPythonWidget
import PySide
PySide.QtSvg = None

from IPython.qt.console.rich_ipython_widget import RichIPythonWidget
from IPython.qt.manager import QtKernelManager
from IPython.qt.client import QtKernelClient
from IPython.lib.kernel import find_connection_file

class IPythonConsole(idaapi.PluginForm):
    
    def __init__(self, connection_file, *args):
        super(IPythonConsole, self).__init__(*args)
        self.connection_file = connection_file
    
    def OnCreate(self, form):
        try:
            self.parent = self.FormToPySideWidget(form, ctx=sys.modules[__name__])
            layout = self._createConsoleWidget()
            self.parent.setLayout(layout)
        except:
            import traceback
            print(traceback.format_exc())

    def _createConsoleWidget(self):
        layout = QtGui.QVBoxLayout()
        connection_file = find_connection_file(self.connection_file)
        self.kernel_manager = QtKernelManager(connection_file=connection_file)
        self.kernel_manager.load_connection_file()
        self.kernel_manager.client_factory = QtKernelClient
        self.kernel_client = self.kernel_manager.client()
        self.kernel_client.start_channels()

        self.ipython_widget = RichIPythonWidget(self.parent)
        self.ipython_widget.kernel_manager = self.kernel_manager
        self.ipython_widget.kernel_client = self.kernel_client
        layout.addWidget(self.ipython_widget)

        return layout

    def Show(self, name="IPython Console"):
        return idaapi.PluginForm.Show(self, name)

    def OnClose(self, form):
        try:
            pass
        except:
            import traceback
            print(traceback.format_exc())

#instance = IPythonConsole()
