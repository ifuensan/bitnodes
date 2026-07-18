"""
Unit tests for sam.py against a scripted fake SAM bridge.

Run: python -m unittest tests.test_sam
"""

import socket
import threading
import unittest

import sam


class FakeSamBridge(threading.Thread):
    """Speaks just enough SAM v3.1 for the client's state machine."""

    def __init__(self, fail_stream_once_with=None):
        super().__init__(daemon=True)
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.endpoint = "127.0.0.1:%d" % self.listener.getsockname()[1]
        self.session_creates = 0
        self.fail_stream_once_with = fail_stream_once_with
        self.echo_payloads = []
        self._stop = False

    def run(self):
        while not self._stop:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        f = conn.makefile("rb")
        try:
            while True:
                line = f.readline()
                if not line:
                    return
                line = line.decode().strip()
                if line.startswith("HELLO"):
                    conn.sendall(b"HELLO REPLY RESULT=OK VERSION=3.1\n")
                elif line.startswith("SESSION CREATE"):
                    self.session_creates += 1
                    conn.sendall(b"SESSION STATUS RESULT=OK DESTINATION=fakedest\n")
                    # Session control socket stays open; keep reading.
                elif line.startswith("NAMING LOOKUP"):
                    name = line.split("NAME=")[1].split(" ")[0]
                    conn.sendall(
                        f"NAMING REPLY RESULT=OK NAME={name} VALUE=b64dest\n".encode()
                    )
                elif line.startswith("STREAM CONNECT"):
                    if self.fail_stream_once_with:
                        result = self.fail_stream_once_with
                        self.fail_stream_once_with = None
                        conn.sendall(f"STREAM STATUS RESULT={result}\n".encode())
                        return
                    conn.sendall(b"STREAM STATUS RESULT=OK\n")
                    # Socket is now the data stream: echo one payload.
                    payload = conn.recv(64)
                    self.echo_payloads.append(payload)
                    conn.sendall(b"echo:" + payload)
                    return
        finally:
            f.close()

    def stop(self):
        self._stop = True
        self.listener.close()


class SamClientTest(unittest.TestCase):
    def setUp(self):
        sam._sessions.clear()
        self.bridge = FakeSamBridge()
        self.bridge.start()
        self.addCleanup(self.bridge.stop)

    def test_stream_connect_returns_data_stream(self):
        sock = sam.stream_connect(
            self.bridge.endpoint, "peer.b32.i2p", timeout=5
        )
        self.addCleanup(sock.close)
        sock.sendall(b"ping")
        self.assertEqual(sock.recv(64), b"echo:ping")
        self.assertEqual(self.bridge.echo_payloads, [b"ping"])

    def test_session_is_reused_across_dials(self):
        s1 = sam.stream_connect(self.bridge.endpoint, "a.b32.i2p", timeout=5)
        self.addCleanup(s1.close)
        s2 = sam.stream_connect(self.bridge.endpoint, "b.b32.i2p", timeout=5)
        self.addCleanup(s2.close)
        self.assertEqual(self.bridge.session_creates, 1)

    def test_invalid_id_drops_session_for_rebuild(self):
        self.bridge.fail_stream_once_with = "INVALID_ID"
        with self.assertRaises(sam.SamError):
            sam.stream_connect(self.bridge.endpoint, "a.b32.i2p", timeout=5)
        self.assertNotIn(self.bridge.endpoint, sam._sessions)
        # Next dial builds a fresh session and succeeds.
        sock = sam.stream_connect(self.bridge.endpoint, "a.b32.i2p", timeout=5)
        self.addCleanup(sock.close)
        self.assertEqual(self.bridge.session_creates, 2)

    def test_stream_failure_raises(self):
        self.bridge.fail_stream_once_with = "CANT_REACH_PEER"
        with self.assertRaises(sam.SamError):
            sam.stream_connect(self.bridge.endpoint, "down.b32.i2p", timeout=5)


if __name__ == "__main__":
    unittest.main()
