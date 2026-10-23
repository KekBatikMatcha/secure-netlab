# Lab topology (Phase 1)

Four segments, one router. Every endpoint reaches other segments only through the router, and the
router forwards only the flows allow-listed in `lab/router/rules.sh`.

```
                         +-------------------------------+
                         |   router (Alpine + iptables)  |
                         |  .1 on every segment          |
                         |  ip_forward=1, FORWARD=DROP   |
                         +--+--------+--------+--------+-+
                            |        |        |        |
   user 10.10.10.0/24  ----+        |        |        |
   server 10.10.20.0/24 -----------+        |        |
   management 10.10.30.0/24 ----------------+        |
   industrial 10.10.40.0/24 -------------------------+

 user (10.10.10.0/24)        user-pc      10.10.10.10   simulated employee PC
 server (10.10.20.0/24)      app-server   10.10.20.10   web app / historian client
 management (10.10.30.0/24)  eng-ws       10.10.30.10   engineering workstation
 industrial (10.10.40.0/24)  plc          10.10.40.10   simulated Modbus/TCP PLC (port 502)
```

## Addressing

| Segment      | Subnet          | Router (.1) | Docker bridge (.254) | Endpoint        |
|--------------|-----------------|-------------|----------------------|-----------------|
| user         | 10.10.10.0/24   | 10.10.10.1  | 10.10.10.254         | user-pc .10     |
| server       | 10.10.20.0/24   | 10.10.20.1  | 10.10.20.254         | app-server .10  |
| management   | 10.10.30.0/24   | 10.10.30.1  | 10.10.30.254         | eng-ws .10      |
| industrial   | 10.10.40.0/24   | 10.10.40.1  | 10.10.40.254         | plc .10         |

The explicit `.254` gateway keeps Docker's bridge address off `.1`, which the router owns.

## Allow / deny matrix

Default policy is DROP. Only these new TCP flows are allowed:

| From        | To          | Port | Purpose                          |
|-------------|-------------|------|----------------------------------|
| user        | server      | 8080 | employees use the web app        |
| management  | server      | 8080 | engineers reach the web app      |
| server      | industrial  | 502  | historian polls the PLC (Modbus) |
| management  | industrial  | 502  | engineers read/write the PLC     |

Everything else is dropped, including user to management, user to industrial, server to management,
and any connection started from industrial. Replies to allowed flows pass through connection
tracking (`ESTABLISHED,RELATED`).

A dropped connection makes the client time out. A refused connection means the flow was allowed but
nothing listened. The tests use that difference to confirm a rule did the blocking.

## How the lab enforces this

1. **Routing:** each endpoint's default route points at its segment router (`ip route replace default
   via ...` in the compose `command`). An endpoint has no other path out.
2. **Filtering:** the router's FORWARD chain applies the allow list above.
3. **No host exposure:** no `ports:` entries. Nothing is reachable from the host or the internet.

## Design notes and findings

- **Networks are not `internal: true`.** With `internal: true`, Docker Desktop's host-side filter
  (`DOCKER-INTERNAL`) dropped every routed packet leaving a segment bridge toward another subnet,
  so the router never received them. The counters showed it: packets dropped on each internal
  bridge. The fix is to leave the networks non-internal and rely on the router-as-gateway
  design above. Containers still have no route out, since the router has no default route.
- **Endpoints get `NET_ADMIN`** only so they can replace their default route. This is lab-only.
- **Simulated Modbus PLC** (`lab/modbus-sim/modbus_server.py`) is standard-library Python.
  It answers function code 3 (read holding registers) and returns Modbus exception responses for
  anything else.

## Verifying it

```
make up          # build and start, waits for healthchecks
make integration # 13 segmentation and Modbus checks against the live lab
```

Expected: `user-pc -> app-server:8080` opens. `user-pc -> plc:502` times out. `eng-ws` reads
`1200 480 3 25 0 0 1 42` from the PLC.
