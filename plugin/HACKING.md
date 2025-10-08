IPyIDA primarily distributes its code via PyPI - this is very convenient.
The IDA Plugin is a trivial stub that refers to the library code.
So, our `ida-plugin.json` metadata file simply has to specify the Python deps and stub entrypoint.

Because hcli will copy the directory containing `ida-plugin.json` into `$IDAUSR/plugins/$plugin-name`,
and we don't want the contents of `ipyida/` there (because that's the library code),
we create this `plugin/` directory with a copy of the stub. Its a tad ugly, but keeps the distribution clean.
There are other options too, but I think they're more invasive.

The IPyIDA authors do a very good job with backwards compatibility, so we don't touch all the other installation code.
The integration with the plugin repo should be a strict enhancement.
