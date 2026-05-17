# multi-sensor-fusion

Linux/Docker rewrite of the BSI Flex 335 v2 SAPIENT middleware stack
([dstl/BSI-Flex-335-v2-Test-Harness/](dstl/BSI-Flex-335-v2-Test-Harness/)
is the upstream Windows reference), plus the supporting platform
services that surround it.

## Run it

```bash
./scripts/build.sh        # regenerate proto bindings + docker compose build
docker compose up -d      # start every service
```

Then open <http://localhost:8080> for the UI (Nodes / Services / Message
/ Tests drawers).

## Run the tests

Either the **Tests** drawer in the UI (click *Run*), or:

```bash
curl -X POST http://127.0.0.1:8094/run            # via HTTP
docker compose exec regression pytest /work/tests # via CLI
```

96 tests covering every library + service end-to-end. The Tests drawer
shows green / yellow / red per file.

## Where things live

See [Architecture.md §10](Architecture.md#10-project-layout-actual) for the
full directory tree. Short version:

* [services/](services/) — every runtime container (UI, Apex, cot-bridge,
  gps, ntp, nodes)
* [libs/](libs/) — shared pip-installable libraries
* [tests/](tests/) — all tests + the regression runner
* [dstl/](dstl/) — vendored upstream sources (read-only)
* [deprecated/](deprecated/) — pre-rewrite code kept for history; not
  built or run
