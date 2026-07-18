"""
Minimal SAM v3.1 client for dialing I2P peers through a local i2pd router.

Modeled on Bitcoin Core's i2p.cpp: one transient STREAM session per process
(tunnel set is built once), then one short-lived control socket per peer dial
that performs HELLO -> NAMING LOOKUP -> STREAM CONNECT and becomes the raw
data stream to the peer. Sockets are ordinary blocking sockets, so gevent's
monkey-patching applies transparently.
"""

import logging
import os
import socket
import threading


class SamError(Exception):
    """Error negotiating with the SAM bridge."""


# endpoint ("host:port") -> (session_id, control_socket). The control socket
# must stay open: SAM destroys the session when it closes.
_sessions = {}
_sessions_lock = threading.Lock()
_session_gen = 0


def _send_line(sock, line):
    sock.sendall(line.encode("ascii") + b"\n")


def _read_line(sock):
    chunks = []
    while True:
        octet = sock.recv(1)
        if not octet:
            raise SamError("connection closed by SAM bridge")
        if octet == b"\n":
            break
        chunks.append(octet)
    return b"".join(chunks).decode("ascii", "replace")


def _request(sock, line, expect_keyword):
    _send_line(sock, line)
    reply = _read_line(sock)
    if expect_keyword not in reply or "RESULT=OK" not in reply:
        raise SamError(f"{line.split(' ')[0]} failed: {reply}")
    return reply


def _reply_value(reply, key):
    for token in reply.split(" "):
        if token.startswith(f"{key}="):
            return token[len(key) + 1 :]
    raise SamError(f"missing {key} in SAM reply: {reply}")


def _connect_bridge(endpoint, timeout):
    host, _, port = endpoint.rpartition(":")
    sock = socket.create_connection((host, int(port)), timeout=timeout)
    sock.settimeout(timeout)
    _request(sock, "HELLO VERSION MIN=3.1 MAX=3.1", "HELLO REPLY")
    return sock


def _session_id(endpoint, timeout):
    global _session_gen
    with _sessions_lock:
        cached = _sessions.get(endpoint)
        if cached is not None:
            return cached[0]
        sock = _connect_bridge(endpoint, timeout)
        _session_gen += 1
        session_id = f"bitnodes-{os.getpid()}-{_session_gen}"
        try:
            _request(
                sock,
                f"SESSION CREATE STYLE=STREAM ID={session_id} "
                "DESTINATION=TRANSIENT SIGNATURE_TYPE=7",
                "SESSION STATUS",
            )
        except (OSError, SamError):
            sock.close()
            raise
        _sessions[endpoint] = (session_id, sock)
        logging.debug("SAM session %s ready on %s", session_id, endpoint)
        return session_id


def _drop_session(endpoint):
    with _sessions_lock:
        cached = _sessions.pop(endpoint, None)
        if cached is not None:
            try:
                cached[1].close()
            except OSError:
                pass


def stream_connect(endpoint, destination, timeout=60):
    """
    Open a stream to destination (a .b32.i2p name) via the SAM bridge at
    endpoint ("host:port"). Returns a connected socket carrying the raw
    byte stream to the I2P peer.
    """
    session_id = _session_id(endpoint, timeout)
    sock = _connect_bridge(endpoint, timeout)
    try:
        lookup = _request(
            sock, f"NAMING LOOKUP NAME={destination}", "NAMING REPLY"
        )
        full_dest = _reply_value(lookup, "VALUE")
        _send_line(
            sock,
            f"STREAM CONNECT ID={session_id} DESTINATION={full_dest} "
            "SILENT=false",
        )
        reply = _read_line(sock)
        if "RESULT=OK" not in reply:
            if "INVALID_ID" in reply:
                # The router lost our session (restart?); rebuild on next dial.
                _drop_session(endpoint)
            raise SamError(f"STREAM CONNECT failed: {reply}")
        return sock
    except BaseException:
        sock.close()
        raise
