#!/usr/bin/env python
# -*- encoding: utf8 -*-
#
# Copyright (c) 2016-2018 ESET
# Author: Marc-Etienne M.Léveillé <leveille@eset.com>
# See LICENSE file for redistribution.

from setuptools import setup, Command

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

class HcliBuild(Command):
  # See https://hcli.docs.hex-rays.com/reference/plugin-packaging-and-format/
  description = "Create a ZIP file for Hex-Rays' hcli to install the plugin"

  user_options = [
    ('dist-dir=', 'd', "directory to put final zip in"),
  ]

  def initialize_options(self):
    self.dist_dir = None

  def finalize_options(self):
    self.set_undefined_options('bdist', ('dist_dir', 'dist_dir'))


  def _build_plugin_manifest(self):
    return {
      "$schema": "https://hcli.docs.hex-rays.com/schemas/ida-plugin.json",
      "IDAMetadataDescriptorVersion": 1,
      "plugin": {
        "name": self.distribution.get_name(),
        "entryPoint": "ipyida_plugin_stub.py",
        "version": self.distribution.get_version(),
        "description": self.distribution.get_description(),
        "license": self.distribution.get_license(),
        "urls": {
          "repository": self.distribution.get_url()
        },
        "authors": [
          {
            "name": self.distribution.get_author(),
            "email": self.distribution.get_author_email()
          }
        ],
        "pythonDependencies": [
          self.distribution.get_name() + "==" + self.distribution.get_version()
        ],
        "categories": [
          "api-scripting-and-automation"
        ],
        "keywords": [
          "ipython",
          "jupyter",
          "console",
          "qtconsole",
          "interactive",
          "python",
          "notebook",
          "kernel",
          "repl"
        ]
      }
    }

  def run(self):
    import zipfile, json, os, distutils

    dist_path = os.path.join(
      self.dist_dir,
      "ipyida-{}.zip".format(self.distribution.get_version())
    )
    manifest = self._build_plugin_manifest()
    stub_file_name = manifest['plugin']['entryPoint']
    with zipfile.ZipFile(dist_path, "w") as z:
      z.writestr("ida-plugin.json", json.dumps(manifest, indent=2).encode())
      z.write(os.path.join("ipyida", stub_file_name), stub_file_name)
    distutils.log.info("Plugin written at " + dist_path)

setup(name='ipyida',
      version='2.3',
      description='IDA plugin to embed the IPython console inside IDA',
      long_description=long_description,
      long_description_content_type="text/markdown",
      author='Marc-Etienne M.Léveillé',
      author_email='leveille@google.com',
      url='https://github.com/eset/ipyida',
      packages=['ipyida'],
      cmdclass={
        'build_hcli': HcliBuild
      },
      install_requires=[
          'ipykernel>=4.6',
          'ipykernel>=5.1.4; python_version >= "3.8" and platform_system=="Windows"',
          'qtconsole>=4.3',
          'qasync; python_version >= "3"',
          'jupyter-client<6.1.13',
          'nbformat',
      ],
      extras_require={
          "notebook": [
              "notebook<7",
              "jupyter-kernel-proxy",
          ]
      },
      license="BSD-2-Clause",
      classifiers=[
          "Development Status :: 5 - Production/Stable",
          "Environment :: Plugins",
          "Programming Language :: Python :: 2.7",
          "Programming Language :: Python :: 3",
      ],
)
