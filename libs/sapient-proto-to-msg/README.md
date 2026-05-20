# sapient-proto-to-msg

Converts SAPIENT `.proto` files from
[`dstl/SAPIENT-Proto-Files/`](../../dstl/SAPIENT-Proto-Files/) (single
source of truth) into the importable `sapient_msg/` package that
services consume.

```
libs/sapient-proto-to-msg/
├── README.md
├── Dockerfile                  ← build-only image; runs the script during build
├── sapient_proto_to_msg.py     ← the codegen recipe
└── sapient_msg/                ← OUTPUT (gitignored; lives inside the proto-gen image)
```

## Usual path: docker compose

```bash
docker compose up -d --build
```

Compose builds the `proto-gen` service first (this `Dockerfile` runs
`sapient_proto_to_msg.py` inside the image, producing `/work/sapient_msg/`).
Every consumer service (`ui`, `cot-bridge`, `regression`) pulls that
folder via `COPY --from=sapient-proto-to-msg /work/sapient_msg`.

## Running the script directly (rare — for debugging)

The script no longer shells out to docker; it calls `grpc_tools.protoc`
in-process. Caller must have the deps installed:

```bash
pip install 'grpcio-tools>=1.60,<1.63' 'protobuf>=4.25,<5'
cd libs/sapient-proto-to-msg
python sapient_proto_to_msg.py                 # uses defaults (v2, dstl/SAPIENT-Proto-Files)
python sapient_proto_to_msg.py --version bsi_flex_335_v1_0
python sapient_proto_to_msg.py --output-dir /tmp/foo
```

Output goes to `<output_dir>/sapient_msg/`.

## Adding another output language

Add an entry to `TARGETS` in `sapient_proto_to_msg.py`:

```python
TARGETS = {"python": "--python_out=.", "go": "--go_out=.", "rust": "--rust_out=."}
```

Then `python sapient_proto_to_msg.py --lang go --output-dir ../sapient-msg-go`.
