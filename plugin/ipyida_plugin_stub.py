# -*- encoding: utf8 -*-
#
# Simple stub to drop in IDA's "plugins" directory.
#
# Copyright (c) 2016-2018 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.
from __future__ import print_function

try:
    from ipyida.ida_plugin import PLUGIN_ENTRY, IPyIDAPlugIn
except ImportError:
    print("[WARN] Could not load IPyIDA plugin. ipyida Python package " \
          "doesn't seem to be installed.")
