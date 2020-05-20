#!/usr/bin/env python
# -*- encoding: utf8 -*-
#
# Copyright (c) 2016-2018 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

from setuptools import setup

long_description = \
"""
IPyIDA
======
IPyIDA is a python-only solution to add an IPython console to IDA Pro. Use
`<Shift-.>` to open a window with an embedded _Qt console_. You can then
benefit from IPython's autocompletion, online help, monospaced font input
field, graphs, and so on.

See full README on GitHub: <https://www.github.com/eset/ipyida>.
"""

setup(name='ipyida',
      version='1.4',
      description='IDA plugin to embed the IPython console inside IDA',
      long_description=long_description,
      long_description_content_type="text/markdown",
      author='Marc-Etienne M.Léveillé',
      author_email='leveille@eset.com',
      url='https://www.github.com/eset/ipyida',
      packages=['ipyida'],
      install_requires=[
          'ipykernel>=4.6, <5',
          'qtconsole>=4.3, <4.7'
      ],
      license="BSD",
      classifiers=[
          "Development Status :: 5 - Production/Stable",
          "Environment :: Plugins",
          "License :: OSI Approved :: BSD License",
          "Programming Language :: Python :: 2.7",
          "Programming Language :: Python :: 3",
      ],
)
