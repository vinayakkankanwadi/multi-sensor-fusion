# Multi-Sensor Fusion — Architecture

## 1. Purpose

This repository delivers a Linux-first, container-based reimplementation of the
SAPIENT BSI Flex 335 v2.0 stack. The upstream reference
([`BSI-Flex-335-v2-Test-Harness/`](BSI-Flex-335-v2-Test-Harness/)) is Windows-only
(WinForms, .NET on Windows, hard-pinned PostgreSQL 12) and cannot run on Ubuntu
or Nvidia Orin. The rewrite preserves wire compatibility with that reference so
existing SAPIENT components can interoperate unchanged.

Build order:

1. **Middleware** (this iteration) — the "message handling application" of the
   spec. Persists and forwards SAPIENT messages between edge nodes and a fusion
   node.
2. **Edge node** — replaces the reference `SapientAsmSimulator`.
3. **Fusion node** — replaces the reference `SapientDmmSimulator`. Will use
   [Stone-Soup](https://stonesoup.readthedocs.io/) for multi-target tracking.
4. **GUI** — implementation-specific per the spec; visualisation and
   tasking/alert-ack input. Not in scope for this iteration but designed for.

Language: **Python 3.12+**, asyncio, asyncpg, generated protobuf bindings.
Single Python runtime across middleware, edge, and fusion (Stone-Soup is
Python).

## 2. Conformance to BSI Flex 335 v2.0

The implementation conforms to the spec sections listed below. Where the
upstream reference deviates from the spec, the rewrite follows the spec.

| Spec section | Requirement | Implementation |
|---|---|---|
| §0.4 | Middleware is **transparent**: stores/forwards but does not modify message content | Enforced — no `Location`/`RangeBearing`/`NodeId` mutation. Reference's `CartesianOffset`/`BearingOffset` and `fixedAsmId` rewrite are dropped. |
| §4.1 | TCP/IP, NTP-synced clocks, Protobuf v3, UUID `node_id`, ULID `report_id` | TCP server/client; container relies on host NTP; `protoc` generates Python bindings; `node_id` validated as UUID; `report_id` validated as ULID. |
| §4.2 | 4-byte little-endian length prefix per message | Length-prefix framer (mirrors `ByteDataMessageBuilder.cs` semantics). |
| §4.4 | Initialization: register → ack → first status | Implemented in connection state machine. |
| §4.5 | Normal operation: status, detection, task, taskAck, alert | Per-content-case routing. |
| §4.6 | Alert process with alert-ack accept/reject | Alert and AlertAck both persisted (the reference does not persist AlertAck — known issue). |
| §4.7 | Task / TaskAck round-trip | Implemented. |
| §4.8 | Shutdown sends Status with `system=GOODBYE` | Edge-node responsibility; middleware logs and removes registration. |
| §4.9 | 10s reconnect retry; <2 min reconnect skips re-registration | In-memory registry with TTL keyed by `node_id`. |
| §4.10 | Platforms (POINTABLE_NODE / MOBILE_NODE) | Carried transparently in registration; no special handling. |
| §4.11 | Hierarchical fusion nodes | Supported by treating a child fusion node as just another registered node. |
| §6 | Outer message types | All nine `oneof content` cases are routed and persisted. |

## 3. System context

```mermaid
flowchart LR
    subgraph Edge["Edge Tier (per platform / sensor)"]
        EN1["Edge Node 1<br/>(sensor)"]
        EN2["Edge Node 2<br/>(sensor)"]
        EN3["Edge Node 3<br/>(effector)"]
    end

    MW["Middleware<br/>(message handling app)"]
    DB[("PostgreSQL")]
    FN["Fusion Node<br/>(Stone-Soup)"]
    GUI["GUI<br/>(future)"]

    EN1 -- "BSI Flex 335 v2 / TCP" --> MW
    EN2 -- "BSI Flex 335 v2 / TCP" --> MW
    EN3 -- "BSI Flex 335 v2 / TCP" --> MW
    MW <-- "BSI Flex 335 v2 / TCP" --> FN
    MW --> DB
    GUI -. "future" .-> MW
    GUI -. "future" .-> DB
```

The fusion node behaves as the **server** for tasking; edge nodes and the
middleware are clients of one another depending on direction. The middleware
never alters message content — it persists, indexes, and forwards.

## 4. Container topology

Each box below is a Docker container. The middleware and database run in
this iteration; edge/fusion/gui are scaffolded for the future.

```mermaid
flowchart TB
    subgraph Compose["docker-compose"]
        direction TB
        MW["middleware<br/>(python:3.12-slim)<br/>:14000 edge-facing<br/>:12010 fusion-facing"]
        DB[("postgres:16<br/>:5432")]
        EN["edge-node<br/>(future)"]
        FN["fusion-node<br/>(future)"]
        GUI["gui<br/>(future)"]
    end

    MW -- "asyncpg" --> DB
    EN -- "TCP 14000" --> MW
    FN -- "TCP 12010" --> MW
    GUI -. "REST/WS (future)" .-> MW
    GUI -. "read-only SQL (future)" .-> DB
```

Notes:

- The reference pins PostgreSQL 12. We use 16 because we own the schema and
  parameterise everything (the reference's raw-SQL approach is a
  documented SQL-injection risk).
- NTP is the **host's** responsibility; containers inherit the kernel clock.
  Document `chronyd`/`systemd-timesyncd` as a deploy prerequisite.

## 5. Middleware — internal design

```mermaid
flowchart TB
    subgraph MW["Middleware container"]
        direction TB
        ES["Edge-facing TCP server<br/>:14000"]
        FS["Fusion-facing TCP client/server<br/>:12010"]
        FR["Length-prefix framer<br/>(4-byte LE)"]
        PB["Protobuf parse<br/>(SapientMessage)"]
        REG["Node registry<br/>(in-memory, TTL)"]
        DISP["Dispatcher<br/>(oneof content)"]
        PERS["Persister<br/>(asyncpg, parameterised)"]
        FWD["Forwarder<br/>(transparent)"]
        HB["Heartbeat / health<br/>(5s tick)"]
    end

    ES --> FR --> PB --> DISP
    FS --> FR
    DISP --> REG
    DISP --> PERS
    DISP --> FWD
    PERS --> DBOUT[("PostgreSQL")]
    FWD --> FS
    HB --> REG
    HB --> DBOUT
```

Component responsibilities:

- **Edge-facing TCP server**: accepts edge-node connections; one task per
  connection.
- **Fusion-facing endpoint**: in MHA mode the middleware acts as a client of
  the fusion node (so the fusion node is "the server" per spec §0.4); a config
  flag also lets it listen if needed.
- **Framer**: reads the 4-byte little-endian length prefix and yields exact
  message frames. Mirrors the semantics of
  [`ByteDataMessageBuilder.cs`](BSI-Flex-335-v2-Test-Harness/SAPIENTMessageProcessor/ByteDataMessageBuilder.cs).
- **Dispatcher**: switches on `SapientMessage.WhichOneof('content')` and runs
  the appropriate handler. No mutation of the message.
- **Registry**: tracks `node_id → (last_seen, capabilities, registered_at)`.
  Honours §4.9 reconnection grace (2 min). On shutdown (Status `system=GOODBYE`),
  drop the entry.
- **Persister**: writes the canonical message + extracted indexed columns to
  Postgres in a single transaction per message. Uses parameterised SQL
  exclusively.
- **Forwarder**: passes messages through unmodified to the fusion node (or to
  the appropriate edge node for Task / RegistrationAck / AlertAck).
- **Heartbeat**: 5s tick recording connection counts and latency to the
  `middleware_log` table; used by GUI dashboards later.

## 6. Message lifecycle

### 6.1 Registration → first status

```mermaid
sequenceDiagram
    autonumber
    participant EN as Edge Node
    participant MW as Middleware
    participant DB as Postgres
    participant FN as Fusion Node

    EN->>MW: TCP connect
    EN->>MW: Registration (node_id=UUID)
    MW->>DB: INSERT registration
    MW->>FN: Registration (forward, unchanged)
    FN->>MW: RegistrationAck
    MW->>DB: INSERT registration_ack
    MW->>EN: RegistrationAck (forward, unchanged)
    EN->>MW: StatusReport
    MW->>DB: INSERT status_report
    MW->>FN: StatusReport (forward, unchanged)
```

### 6.2 Detection / task / taskAck

```mermaid
sequenceDiagram
    autonumber
    participant EN as Edge Node
    participant MW as Middleware
    participant DB as Postgres
    participant FN as Fusion Node

    EN->>MW: DetectionReport (report_id=ULID)
    MW->>DB: INSERT detection_report
    MW->>FN: DetectionReport (forward)

    FN->>MW: Task (destination_id=EN.node_id)
    MW->>DB: INSERT task
    MW->>EN: Task (forward to destination)
    EN->>MW: TaskAck
    MW->>DB: INSERT task_ack
    MW->>FN: TaskAck (forward)
```

### 6.3 Alert and alert-ack

```mermaid
sequenceDiagram
    autonumber
    participant EN as Edge Node
    participant MW as Middleware
    participant DB as Postgres
    participant FN as Fusion Node

    EN->>MW: Alert
    MW->>DB: INSERT alert
    MW->>FN: Alert (forward)
    FN->>MW: AlertAck (status=accept|reject)
    MW->>DB: INSERT alert_ack  (reference omits this — fixed here)
    MW->>EN: AlertAck (forward)
```

### 6.4 Lost connection (§4.9)

```mermaid
sequenceDiagram
    autonumber
    participant EN as Edge Node
    participant MW as Middleware

    Note over EN,MW: Connection drops
    EN-->>MW: TCP RST / timeout
    MW->>MW: Mark node disconnected;<br/>retain registry entry for 2 min

    loop every 10s
        EN->>MW: TCP connect attempt
    end

    alt Reconnect within 2 min
        EN->>MW: StatusReport (no re-register)
        MW->>MW: Refresh last_seen
    else Reconnect after 2 min
        EN->>MW: Registration (mandatory)
    end
```

## 7. Wire format

Every byte stream consists of repeated frames:

```
+--------+------+------+------+------+------+------+------+------+
| len    | byte | byte | ...  | byte |  len | byte | byte | ...  |
| (4 LE) |  1   |  2   |  ... |  N   | (4LE)|  1   |  2   |  ... |
+--------+------+------+------+------+------+------+------+------+
| <----- protobuf SapientMessage -----> |
```

- `len` = 32-bit little-endian, payload length in bytes (excludes the 4-byte
  prefix). Per spec §4.2; this differs from standard Google framing.
- Payload = a `SapientMessage` (see [sapient_message.proto](SAPIENT-Proto-Files/bsi_flex_335_v2_0/sapient_message.proto)).
  Mandatory fields: `timestamp`, `node_id`, exactly one of the `content` oneof.

## 8. Database schema (sketch)

One table per outer message, plus indexes. Key columns are typed so we can
query without reaching back into the protobuf payload.

| Table | Purpose | Key columns |
|---|---|---|
| `registration` | Edge-node registrations | `key_id`, `message_time`, `node_id`, `node_type[]`, `icd_version`, `payload_pb` |
| `registration_ack` | Acks from fusion | `key_id`, `message_time`, `node_id`, `destination_id`, `payload_pb` |
| `status_report` | Periodic status | `key_id`, `report_time`, `node_id`, `report_id` (ULID), `system`, `payload_pb` |
| `detection_report` | Detections | `key_id`, `report_time`, `node_id`, `report_id`, `object_id`, `location_geom`, `payload_pb` |
| `task` | Tasks from fusion | `key_id`, `message_time`, `task_id`, `node_id`, `destination_id`, `payload_pb` |
| `task_ack` | Edge taskAcks | `key_id`, `message_time`, `task_id`, `node_id`, `task_status`, `payload_pb` |
| `alert` | Edge alerts | `key_id`, `alert_time`, `node_id`, `alert_id`, `priority`, `payload_pb` |
| `alert_ack` | Fusion alert responses | `key_id`, `message_time`, `alert_id`, `node_id`, `status`, `payload_pb` |
| `error` | Error messages | `key_id`, `message_time`, `node_id`, `payload_pb` |
| `middleware_log` | Connection counts, latency | `tick_time`, `num_edges`, `num_fusion`, `comms_latency_ms`, `db_latency_ms` |

`payload_pb` is the raw `SapientMessage` bytes, allowing lossless replay and
audit. Geographic columns use PostGIS where applicable.

Tables omitted from the reference and not reintroduced:

- `objective`, `route_plan` ("Zodiac" tables — not in BSI Flex 335 v2).
- `sensor_location_offset` — only existed to drive `CartesianOffset` mutation,
  which the middleware no longer performs.

## 9. Tech stack

| Concern | Choice | Why |
|---|---|---|
| Language | Python 3.12 | Shared runtime with future fusion (Stone-Soup) and edge nodes |
| Async runtime | `asyncio` | Native, fits TCP server workloads |
| Database driver | `asyncpg` | Fastest PG driver in Python; native parameterisation |
| Protobuf | `protobuf` + `protoc` v3 | BSI Flex requires protobuf v3 |
| Logging | `structlog` (JSON) | Container-friendly structured logs |
| Config | env vars + `pydantic-settings` | 12-factor; matches container deploys |
| DB | PostgreSQL 16 (+ PostGIS) | We own the schema; modern PG is fine |
| Container base | `python:3.12-slim` | Small, multi-arch (linux/amd64, linux/arm64 for Orin) |
| Orchestration | `docker compose` (dev), TBD (prod) | Compose for the local dev/test loop |

## 10. Project layout (target)

```
multi-sensor-fusion/
├── Architecture.md                  this document
├── docker-compose.yml               middleware + db + (later) edge/fusion/gui
├── proto/                           generated Python bindings checked in
├── middleware/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── src/middleware/
│   │   ├── __main__.py              entrypoint
│   │   ├── config.py                pydantic-settings
│   │   ├── framing.py               4-byte LE length prefix codec
│   │   ├── tcp/
│   │   │   ├── server.py            edge-facing
│   │   │   └── client.py            fusion-facing
│   │   ├── dispatch.py              oneof switch → handlers
│   │   ├── handlers/                one per outer message
│   │   ├── registry.py              node_id → state, TTL
│   │   ├── persistence/             asyncpg + parameterised SQL
│   │   ├── forwarder.py             transparent forwarding
│   │   └── health.py                heartbeat tick
│   └── tests/
├── db/
│   ├── Dockerfile                   postgres:16 + PostGIS + init SQL
│   └── init/                        schema + indices
├── edge-node/                       future
├── fusion-node/                     future
├── gui/                             future
├── compat-baseline/                 see §13
├── BSI-Flex-335-v2-Test-Harness/    upstream reference (unchanged)
├── SAPIENT-Proto-Files/             upstream protos (unchanged)
├── Stone-Soup/                      vendored for future fusion node
└── spec/
    └── bsi-flex-335.pdf
```

## 11. Deviations from the upstream reference (intentional)

| Reference behavior | Rewrite | Rationale |
|---|---|---|
| WinForms GUI in the same process | Headless service; GUI is a separate future container | Spec §0.4: GUI is implementation-specific. Linux container can't host WinForms. |
| `CartesianOffset` / `BearingOffset` mutate Location/RangeBearing | Removed | Spec §0.4 NOTE 2: middleware must be transparent. |
| `fixedAsmId` rewrites incoming `node_id` | Removed | Same — transparency. |
| Two binaries (`SDA` / `DMM-DA`) selected by `DMM` flag | Single middleware service with edge-facing + fusion-facing endpoints | Reference split was a Windows-process-isolation artefact; unnecessary in containers. |
| Raw SQL string concatenation | `asyncpg` parameterised statements only | Reference's README acknowledges SQL-injection risk. |
| `objective`, `route_plan` tables ("Zodiac") | Dropped | Not part of BSI Flex 335 v2. |
| Alert ack not persisted (known issue) | Persisted in `alert_ack` table | Spec §4.6. |
| PostgreSQL 12 hard-pin | PostgreSQL 16 | We own the schema; no PG-12-specific features used. |
| `app.config` XML application settings | Env vars + pydantic-settings | 12-factor. |
| log4net XML | `structlog` JSON | Container-friendly. |

## 12. GUI (future, not yet in scope)

The spec leaves the GUI as implementation-specific. Planned shape:

- Separate container, web-based (probably FastAPI + a SPA — to be decided).
- Read-only access to Postgres for live dashboards (connection counts, latency,
  detection map).
- Outbound channel through the middleware for Task issuance and AlertAck, so
  the GUI never speaks BSI Flex 335 directly to edge nodes.

```mermaid
flowchart LR
    Browser["Browser"] -- HTTPS --> GUI["gui (future)"]
    GUI -- read-only SQL --> DB[("PostgreSQL")]
    GUI -- internal API --> MW["Middleware"]
    MW -- "Task / AlertAck" --> EN["Edge Node"]
```

## 13. Compatibility baseline against the Windows reference

Because the user has a Windows instance, we lock down behavior with baselines
captured from the reference Windows harness, which we then replay against the
new Python middleware. Details, scripts, and artifacts live under
[`compat-baseline/`](compat-baseline/).

```mermaid
flowchart LR
    subgraph Win["Windows VM (dev-time only)"]
        AsmSim["SapientAsmSimulator"]
        SDA["SapientDataAgent (SDA)"]
        DMM["SapientDataAgent (DMM)"]
        DmmSim["SapientDmmSimulator"]
        PG12[("PostgreSQL 12")]
        AsmSim --> SDA --> DMM --> DmmSim
        SDA --> PG12
        DMM --> PG12
    end

    Win -.->|pcap, pg_dump, logs| Artifacts["compat-baseline/baselines/"]

    subgraph Linux["Linux dev host"]
        Replay["replay tool"]
        NewMW["new Python middleware"]
        PG16[("PostgreSQL 16")]
        Replay --> NewMW --> PG16
    end

    Artifacts -->|tcp pcap replay| Replay
    Artifacts -->|expected pg state| Diff["state diff"]
    PG16 --> Diff
```

The baseline is not a runtime dependency — it is a regression harness used
during development.

## 14. Roadmap

1. **Iteration 1 — middleware** (current): TCP framer, dispatcher, registry,
   persister, forwarder, health, Postgres schema, container, compose,
   compat-baseline scaffolding (this document and the empty folder).
2. **Iteration 2 — edge node**: a Python edge-node service that registers,
   sends status/detection/alert, accepts tasks. Replaces `SapientAsmSimulator`.
3. **Iteration 3 — fusion node**: Stone-Soup-based fusion that consumes
   detections from the middleware, emits tasks, handles alert-ack. Replaces
   `SapientDmmSimulator`.
4. **Iteration 4 — GUI**: separate container; web UI on top of the database
   and middleware control plane.
5. **Iteration 5 — Orin packaging**: linux/arm64 image builds, NTP/systemd
   integration, deploy docs.
