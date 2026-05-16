# -*- encoding: utf8 -*-
#
# Wrapper around ``jupyter_kernel_proxy`` that patches its fallback
# ``kernel_info_reply`` so the JupyterLab/Notebook 7 debug button stays
# enabled when a real kernel is already connected to the proxy.
#
# ``jupyter_kernel_proxy.KernelProxyManager._send_proxy_kernel_info`` is a
# 3-second fallback: if the real kernel does not reply to ``kernel_info_request``
# within that window the proxy synthesises a minimal reply that lacks the
# ``debugger`` field (and others). On notebook 7 / JupyterLab the debug
# button is enabled based on ``kernel_info_reply.debugger`` -- the
# fallback racing the real reply silently disables it.
#
# This wrapper suppresses the fallback when a real ``proxy_target`` is
# connected, so the front-end always sees the real kernel's reply.

import sys

import jupyter_kernel_proxy


_orig_send_proxy_kernel_info = (
    jupyter_kernel_proxy.KernelProxyManager._send_proxy_kernel_info
)


def _patched_send_proxy_kernel_info(self, request):
    if getattr(self.server, "proxy_target", None) is not None:
        # Real kernel will answer; do not race it with a stripped-down
        # fallback reply that drops the ``debugger`` flag.
        return
    return _orig_send_proxy_kernel_info(self, request)


jupyter_kernel_proxy.KernelProxyManager._send_proxy_kernel_info = (
    _patched_send_proxy_kernel_info
)


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m ipyida.proxy_runner <connection_file>")
        sys.exit(1)
    jupyter_kernel_proxy.start(sys.argv[1])


if __name__ == "__main__":
    main()
