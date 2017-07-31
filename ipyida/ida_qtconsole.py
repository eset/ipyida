# -*- encoding: utf8 -*-
#
# This module integreate a qtconsole to the IDA GUI.
# See README.adoc for more details.
#
# Copyright (c) 2015 Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

import idaapi

def is_using_pyqt5():
    if hasattr(idaapi, "get_kernel_version"):
        _ida_version_major, _ida_version_minor = map(int, idaapi.get_kernel_version().split("."))
        return _ida_version_major > 6 or (_ida_version_major == 6 and _ida_version_minor >= 9)
    else:
        return False

if is_using_pyqt5():
    from PyQt5 import QtGui, QtWidgets
else:
    from PySide import QtGui

import sys

# QtSvg binairies are not bundled with IDA. So we monkey patch PySide to avoid
# IPython to load a module with missing binary files. This *must* happend before
# importing RichJupyterWidget
if is_using_pyqt5():
    # In the case of pyqt5, we have to avoid patch the binding detection too.
    import qtconsole.qt_loaders
    original_has_binding = qtconsole.qt_loaders.has_binding
    def hooked_has_bindings(arg):
        if arg == 'pyqt5':
            return True
        else:
            return original_has_binding(arg)
    qtconsole.qt_loaders.has_binding = hooked_has_bindings
    import PyQt5
    PyQt5.QtSvg = None
    class Empty: pass
    PyQt5.QtPrintSupport = Empty()
else:
    import PySide
    PySide.QtSvg = None
    class Empty: pass
    PySide.QtPrintSupport = Empty()

from qtconsole.rich_jupyter_widget import RichJupyterWidget
from qtconsole.manager import QtKernelManager
from qtconsole.client import QtKernelClient
from jupyter_client import find_connection_file

class IPythonConsole(idaapi.PluginForm):
    
    def __init__(self, connection_file, *args):
        super(IPythonConsole, self).__init__(*args)
        self.connection_file = connection_file
    
    def OnCreate(self, form):
        try:
            if is_using_pyqt5():
                self.parent = self.FormToPyQtWidget(form, ctx=sys.modules[__name__])
            else:
                self.parent = self.FormToPySideWidget(form, ctx=sys.modules[__name__])
            layout = self._createConsoleWidget()
            self.parent.setLayout(layout)
        except:
            import traceback
            print(traceback.format_exc())

    def _createConsoleWidget(self):
        if is_using_pyqt5():
            layout = QtWidgets.QVBoxLayout()
        else:
            layout = QtGui.QVBoxLayout()
        connection_file = find_connection_file(self.connection_file)
        self.kernel_manager = QtKernelManager(connection_file=connection_file)
        self.kernel_manager.load_connection_file()
        self.kernel_manager.client_factory = QtKernelClient
        self.kernel_client = self.kernel_manager.client()
        self.kernel_client.start_channels()

        self.ipython_widget = RichJupyterWidget(self.parent)
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

