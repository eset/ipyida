# -*- encoding: utf8 -*-
#
# Automate the installation of pip and IPyIDA.
#
# Copyright (c) 2016 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

import idaapi
import os
import sys

if not "IPYIDA_PACKAGE_LOCATION" in dir():
    IPYIDA_PACKAGE_LOCATION ="https://github.com/eset/ipyida/archive/stable.tar.gz"


# Fix the sys.exectuable path. It's misleading in two cases:
#  - On Windows, it's set to 'idaq.exe'.
#  - If a virtualenv is activated with activate_this.py, sys.prefix is changed
#    but sys.executable is still set to the original process. pip and packages
#    will not install in the virtualenv if we don't set it right.
if not hasattr(sys, 'real_executable'):
    sys.real_executable = sys.executable
    if sys.platform == 'win32':
        sys.executable = os.path.join(sys.prefix, 'Python.exe')
    else:
        sys.executable = os.path.join(sys.prefix, 'bin', 'python')

try:
    import pip
    print("[+] Using already installed pip (version {:s})".format(pip.__version__))
except ImportError:
    print("[+] Installing pip")
    import urllib2
    import subprocess
    get_pip = urllib2.urlopen("https://bootstrap.pypa.io/get-pip.py").read()
    stdout = None
    if sys.platform != "win32":
        stdout = sys.stdout
    p = subprocess.Popen(
        sys.executable,
        stdin=subprocess.PIPE,
        stdout=stdout
    )
    p.communicate(get_pip)
    try:
        import pip
    except:
        print("[-] Could not install pip.")
        raise


if pip.main(["install", "-U", IPYIDA_PACKAGE_LOCATION]) != 0:
    print("[-] ipyida package installation failed")
    raise Exception("ipyida package installation failed")


if not os.path.exists(idaapi.get_user_idadir()):
    os.path.makedirs(idaapi.get_user_idadir(), 0755)

ida_python_rc_path = os.path.join(idaapi.get_user_idadir(), "idapythonrc.py")
rc_file_content = ""

if os.path.exists(ida_python_rc_path):
    with file(ida_python_rc_path, "r") as rc:
        rc_file_content = rc.read()

if "# BEGIN IPyIDA loading" in rc_file_content:
    print("[+] IPyIDA loading script already present in idapythonrc.py")
else:
    with file(ida_python_rc_path, "a") as rc:
        rc.write("\n")
        rc.write("# BEGIN IPyIDA loading code\n")
        rc.write("try:\n")
        rc.write("  import ipyida.ida_plugin\n")
        rc.write("  ipyida.ida_plugin.load()\n")
        rc.write("except:\n")
        rc.write("  print \"Could not load IPyIDA plugin. Verify that the \"\n")
        rc.write("  print \"ipyida python package is installed.\"\n")
        rc.write("# END IPyIDA loading code\n")
    print("[+] IPyIDA loading script already added to idapythonrc.py")

import ipyida.ida_plugin
ipyida.ida_plugin.load()

if os.name == 'nt':
    # No party for Windows
    print("[+] IPyIDA Installation successful.")
else:
    print("[🍺] IPyIDA Installation successful.")
