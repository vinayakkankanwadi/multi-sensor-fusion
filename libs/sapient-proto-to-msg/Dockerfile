# proto-gen — runs sapient_proto_to_msg.py during build so that
# every consumer Dockerfile can `COPY --from=sapient-proto-to-msg`
# the generated `sapient_msg/` package without any host-side codegen
# step. Wired into compose as a build-only service (see compose's
# `proto-gen:` entry); never started as a long-running container.

FROM python:3.12-slim

RUN pip install --no-cache-dir \
        'setuptools<70' \
        'grpcio-tools>=1.60,<1.63' \
        'protobuf>=4.25,<5'

WORKDIR /work

# The script does the actual protoc work.
COPY sapient_proto_to_msg.py /work/

# Proto sources come from dstl/SAPIENT-Proto-Files/ via compose's
# `additional_contexts: proto-sources: ./dstl/SAPIENT-Proto-Files`.
COPY --from=proto-sources . /work/proto-sources/

RUN python sapient_proto_to_msg.py --proto-dir=/work/proto-sources --output-dir=/work
