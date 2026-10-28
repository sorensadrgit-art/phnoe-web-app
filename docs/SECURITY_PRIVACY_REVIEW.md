# KineLab PT — Security & Privacy Architecture Review

## 1. Executive Summary
KineLab PT is designed as an offline-first, local-workstation research software package. It enforces strict boundary controls to protect participant privacy, prevent unauthorized local network access, and maintain the integrity of clinical biomechanics research data.

## 2. Threat Model & Boundaries

### 2.1 Network Exposure
- **Localhost Exclusive Binding**: The backend HTTP service (`t6_server.py`) binds strictly to `127.0.0.1`. It NEVER binds to `0.0.0.0` or external network interfaces.
- **Port Allocation**: Dynamically selects an available port in the restricted range `4184–4204`. If no port in this range is free, the launcher aborts rather than selecting an unrestricted system port.
- **No Remote Telemetry or Cloud Calls**: The application makes zero outbound internet requests. No analytics, tracking scripts, CDN fetches, or remote API endpoints exist in the codebase.

### 2.2 Authentication & Token Transport
- **Cryptographic Ephemeral Token**: Upon server launch, a 32-byte (64-character hex) cryptographically secure random token is generated via `secrets.token_hex(32)`.
- **URL Fragment Transport**: When the launcher opens the default browser, the access token is passed in the URL fragment (`http://127.0.0.1:4184/#access=<token>`).
  - **Security Guarantee**: Fragments are never sent to the server in HTTP request headers, never appear in server access logs, and never leak through browser referrer headers.
- **API Authorization**: All REST API calls require an `Authorization: Bearer <token>` header matching the instance token. Unauthenticated requests are rejected with HTTP 401 Unauthorized.

### 2.3 Web Application Defenses
- **DNS Rebinding Protection**:
  - The server inspects the `Host` header on all incoming requests.
  - Allowed hosts: `127.0.0.1`, `localhost`, `127.0.0.1:<port>`, `localhost:<port>`.
  - Any request with a spoofed or external host (e.g., `evil.com`, `attacker.local`) is immediately rejected with HTTP 403 Forbidden.
- **Path Traversal & Injection Defenses**:
  - URL-encoded directory traversal attempts (`..%2f`, `%2e%2e%2f`, `..\\`) are rejected.
  - Null-byte injections (`%00`) are rejected.
  - Filesystem serving is strictly confined to resolved, allowlisted subdirectories (`viewer/dist` and verified session output paths).
- **Concurrent Upload Locking**:
  - Upload mutations to the same camera role acquire an in-memory role lock.
  - Colliding requests receive HTTP 409 Conflict without corrupting on-disk files.
- **Oversized Payload TCP Protection**:
  - Payloads exceeding `MAX_JSON` (64 KiB) or `MAX_UPLOAD` (1 GiB) are rejected with HTTP 413.
  - The server drains incoming socket buffers before sending the error response to prevent Windows TCP RST connection aborts.

## 3. Privacy & Data Storage
- **Participant Data Isolation**:
  - Participant video recordings and derived kinematics remain strictly on the local machine in `projects/`.
  - Application settings, instance tokens, and server logs are isolated in `%LOCALAPPDATA%\KineLabPT`.
  - No Protected Health Information (PHI) is ever transmitted, indexed externally, or stored in system-wide public directories.
