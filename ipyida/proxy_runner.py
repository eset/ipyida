# -*- encoding: utf8 -*-
#
# Wrapper around ``jupyter_kernel_proxy`` that patches two behaviours:
#
# (a) ``KernelProxyManager._send_proxy_kernel_info`` is a 3-second fallback:
#     if the real kernel does not reply to ``kernel_info_request`` within
#     that window the proxy synthesises a minimal reply that lacks the
#     ``debugger`` field (and others). On notebook 7 / JupyterLab the debug
#     button is enabled based on ``kernel_info_reply.debugger`` -- the
#     fallback racing the real reply silently disables it.
#
# (b) Clicking "Shutdown" / "Restart" in the JupyterLab kernel menu sends a
#     ``shutdown_request`` on the control (and historically shell) channel.
#     If we forward it, IDA's embedded ipykernel calls ``IOLoop.stop()`` on
#     the kernel's loop, which -- because qasync ties asyncio to IDA's Qt
#     event loop -- tears IDA down with it. Instead we answer locally with
#     ``shutdown_reply`` and drop the message: the notebook server then
#     terminates this proxy subprocess only, and IDA's kernel keeps
#     running. Restart looks the same to the user: the server respawns the
#     proxy, which reconnects to IDA's still-live kernel.

import sys

import jupyter_kernel_proxy
from jupyter_kernel_proxy import KernelProxyManager, JupyterMessage


# --- (a) keep the JupyterLab debug button enabled -------------------------

_orig_send_proxy_kernel_info = KernelProxyManager._send_proxy_kernel_info


def _patched_send_proxy_kernel_info(self, request):
    if getattr(self.server, "proxy_target", None) is not None:
        # Real kernel will answer; do not race it with a stripped-down
        # fallback reply that drops the ``debugger`` flag.
        return
    return _orig_send_proxy_kernel_info(self, request)


KernelProxyManager._send_proxy_kernel_info = _patched_send_proxy_kernel_info


# --- (b) intercept browser-initiated shutdown so IDA survives -------------

def _make_shutdown_interceptor(channel_name):
    def handler(server, target_stream, data):
        msg = JupyterMessage.parse(data)
        restart = (msg.content or {}).get("restart", False)
        reply_stream = getattr(server.streams, channel_name)
        reply_parts = msg.identities + server.make_multipart_message(
            "shutdown_reply",
            {"restart": restart, "status": "ok"},
            parent_header=msg.header,
        )
        reply_stream.send_multipart(reply_parts)
        reply_stream.flush()
        # Return None to drop the request -- do NOT forward to IDA's kernel.
        return None
    return handler


_orig_init = KernelProxyManager.__init__


def _patched_init(self, server):
    _orig_init(self, server)
    self.server.intercept_message(
        "control", "shutdown_request", _make_shutdown_interceptor("control"),
    )
    self.server.intercept_message(
        "shell", "shutdown_request", _make_shutdown_interceptor("shell"),
    )


KernelProxyManager.__init__ = _patched_init


# --- (c) connect deterministically to IDA's kernel ------------------------
#
# ``KernelProxyManager.connect_to_last`` picks the kernel-*.json with the
# newest ``st_atime``, which is fragile: after a few %open_notebook /
# browser-shutdown cycles, stale proxy connection files in
# JUPYTER_RUNTIME_DIR can out-rank IDA's, and the new proxy ends up
# dialing a dead ZMQ endpoint -- the cell shows "no kernel" and never
# replies. The ipyida kernelspec passes IDA's connection-file basename
# as the second positional argv argument; use it to force the
# connection here.

_target_kernel_file = sys.argv[2] if len(sys.argv) > 2 else None

if _target_kernel_file:
    def _patched_connect_to_last(self):
        self.update_running_kernels()
        try:
            self.connect_to(_target_kernel_file)
            return
        except ValueError:
            pass
        # Target not present (yet?) -- fall back to the original
        # newest-by-atime selection so the proxy still has *something*
        # to talk to.
        if self.kernels:
            self.connect_to(next(iter(self.kernels.keys())))

    KernelProxyManager.connect_to_last = _patched_connect_to_last


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m ipyida.proxy_runner "
              "<connection_file> [<ida_kernel_file>]")
        sys.exit(1)
    jupyter_kernel_proxy.start(sys.argv[1])


if __name__ == "__main__":
    main()
