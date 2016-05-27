#!/usr/bin/env python
# -*- encoding: utf8 -*-
#
# Copyright (c) 2016 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

from distutils.core import setup

setup(name='ipyida',
      version='0.9',
      description='IDA plugin to embed the IPython console inside IDA',
      author='Marc-Etienne M.Léveillé',
      author_email='leveille@eset.com',
      url='https://www.github.com/eset/ipyida',
      packages=['ipyida'],
      install_requires=[
          'ipython[qtconsole]==3.2.3',
      ],
      license="BSD",
)