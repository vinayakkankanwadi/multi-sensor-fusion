# tests

The single home for every test in the project — library unit tests
*and* black-box service tests. Both run in one `pytest` invocation under
the `regression` compose service (the runner).

## Layout & naming convention

**Folders are named for what's being tested; files match exactly.**

* `tests/libs/<package>/test_<package>.py` — one test file per library, named after the Python package
* `tests/services/<service>/test_<service>.py` — one test file per docker-compose service, named after the service

```
multi-sensor-fusion/
├── tests/
│   ├── Dockerfile                          (regression runner image)
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── conftest.py                         (shared fixtures: URLs, http, created_node, cot_stats_snapshot, …)
│   ├── README.md
│   ├── libs/                               (library unit tests)
│   │   ├── sapient_encode_decode_msg/test_sapient_encode_decode_msg.py
│   │   ├── sapient_msg_to_cot/test_sapient_msg_to_cot.py
│   │   └── sapient_proto_to_msg/test_sapient_proto_to_msg.py
│   └── services/                           (black-box service tests)
│       ├── conftest.py                     (autouse: wait-for-stack)
│       ├── apex/test_apex.py
│       ├── cot_bridge/test_cot_bridge.py
│       ├── gps/test_gps.py
│       ├── nodes/test_nodes.py
│       ├── ntp/test_ntp.py
│       └── ui/test_ui.py
└── libs/                                   (libraries: code + packaging only, no tests)
    ├── sapient-encode-decode-msg/
    │   ├── pyproject.toml
    │   └── sapient_encode_decode_msg.py    (single-file module)
    ├── sapient-msg-to-cot/
    │   ├── pyproject.toml
    │   ├── README.md
    │   └── sapient_msg_to_cot/             (package source)
    └── sapient-proto-to-msg/
        ├── README.md
        ├── config.yaml
        ├── sapient_proto_to_msg.py         (single Python entry; generates sapient_msg/ on demand)
        └── sapient_msg/                    (gitignored output)
```

## Why this shape

* **Tests live in one place.** `tests/` is the only directory anyone
  scans to ask "what's covered?" or "where do I add a test for X?"
* **Folder names describe what's tested**, not the methodology.
  `tests/services/` (not `tests/regression/`) mirrors `tests/libs/`.
* **One file per testable unit.** Aspects of the same thing live in the
  same file, grouped by header comments.
* **Libraries hold only their code.** `libs/<lib>/` contains the package
  source and a `pyproject.toml`. No tests, no test deps.
* **Black-box only for services.** Tests under `tests/services/` access
  services through their public HTTP/TCP/UDP interfaces. No
  `from app.<svc> import …` anywhere.
* **The runner is lib-agnostic.** `tests/Dockerfile` COPYs the whole
  `libs/` tree once and `pip install`s every lib that has a
  `pyproject.toml`.

## How to run

The `regression` service in compose is the runner. Profile-gated so it
doesn't come up on `docker compose up -d`.

```bash
./scripts/build.sh                          # regen proto bindings + build all images
docker compose up -d                        # bring up the stack
docker compose run --rm regression          # full suite (libs + services), ~31s
```

The runner uses `network_mode: host` and dials `127.0.0.1` on each
service's public port. Override via env vars (`UI_URL`, `NODES_URL`,
`GPS_URL`, `NTP_URL`, `COT_BRIDGE_URL`, `APEX_HOST`, `APEX_PORT`, …)
if testing across a network.

## Subsets

```bash
# one service end-to-end
docker compose run --rm regression pytest -v /work/tests/services/nodes

# one library
docker compose run --rm regression pytest -v /work/tests/libs/sapient_msg_to_cot

# only libs / only services
docker compose run --rm regression pytest -v /work/tests/libs
docker compose run --rm regression pytest -v /work/tests/services

# tests matching a keyword across the whole suite
docker compose run --rm regression pytest -v -k validator
```

## Adding tests

* **Test a library**: add to the existing
  `tests/libs/<package>/test_<package>.py`. New library?
  `mkdir tests/libs/<new>` and create
  `tests/libs/<new>/test_<new>.py`.
* **Test a service**: add to the existing
  `tests/services/<service>/test_<service>.py`. New service?
  `mkdir tests/services/<new>` and create
  `tests/services/<new>/test_<new>.py`. Use the shared fixtures
  (`ui_url`, `created_node`, `cot_stats_snapshot`, …). Never import
  from any `services/<svc>/app/` module.

## Adding a new library

1. `mkdir libs/<name> && cd libs/<name>`
2. Create `<package>/__init__.py` + your code (or a single
   `<package>.py` for tiny libs — see `libs/sapient-encode-decode-msg/`)
3. Create `pyproject.toml`
4. Create `tests/libs/<package>/test_<package>.py`
5. `docker compose build regression && docker compose run --rm regression`

If a service behavior can't be tested black-box because no public
interface exposes it, **add the interface** rather than reaching into
the service. cot-bridge's `/stats` endpoint and the `nodes` service's
`POST /nodes/refresh` were added for exactly this reason.
