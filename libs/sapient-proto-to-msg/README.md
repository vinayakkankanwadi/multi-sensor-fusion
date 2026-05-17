# sapient-proto-to-msg

One Python script. One config file. Converts SAPIENT `.proto` files
from [`dstl/SAPIENT-Proto-Files/`](../../dstl/SAPIENT-Proto-Files/)
(single source of truth) into the importable `sapient_msg/` package
that services consume.

```
libs/sapient-proto-to-msg/
├── README.md
├── config.yaml                  ← what to compile, where to write
├── sapient_proto_to_msg.py      ← run this
└── sapient_msg/                 ← OUTPUT (gitignored; only exists when you run the script)
```

## Run

```bash
cd libs/sapient-proto-to-msg
python sapient_proto_to_msg.py
```

That reads `config.yaml`, runs `protoc` inside an ephemeral
`python:3.12-slim` container (only docker is required on the host), and
writes `sapient_msg/` in this folder. Defaults are v2-only; override
per-invocation:

```bash
python sapient_proto_to_msg.py --version bsi_flex_335_v1_0
python sapient_proto_to_msg.py --output-dir /tmp/foo --lang python
```

The output is **not committed** — `sapient_msg/` is gitignored at the
repo root. Re-run whenever the `.proto` sources change or before
building any service that consumes it. (`scripts/build.sh` does this
automatically.)

## Adding another output language

Add a target to `TARGETS` in `sapient_proto_to_msg.py`:

```python
TARGETS = {
    "python": "--python_out=.",
    "go":     "--go_out=.",
    "rust":   "--rust_out=.",
}
```

Then `python sapient_proto_to_msg.py --lang go --output-dir ../sapient-msg-go`.

## What consumes it

Every service that needs SAPIENT bindings declares
`sapient-proto-to-msg: ./libs/sapient-proto-to-msg` as a Docker
additional_context and `COPY --from=sapient-proto-to-msg sapient_msg`
into its image. The regression test image does the same to a known
location on PYTHONPATH.
