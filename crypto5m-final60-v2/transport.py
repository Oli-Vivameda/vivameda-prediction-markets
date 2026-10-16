"""Existing BTC public WebSocket transport, extracted without application imports."""
import base64
import hashlib
import os
import socket
import ssl
import struct
UA='VivamedaPaperResearch/1.0'
class PublicSocket:
    """Minimal RFC6455 client for the legacy public RTDS feed; no credentials."""
    def __init__(self, host='ws-live-data.polymarket.com', path='/'):
        self.s = ssl.create_default_context().wrap_socket(
            socket.create_connection((host, 443), timeout=8),
            server_hostname=host)
        self.s.settimeout(8)
        key = base64.b64encode(os.urandom(16)).decode()
        request = (f'GET {path} HTTP/1.1\r\nHost: {host}\r\n'
                   'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                   f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                   f'User-Agent: {UA}\r\n\r\n')
        self.s.sendall(request.encode())
        header = bytearray()
        while not header.endswith(b'\r\n\r\n') and len(header) < 16384:
            chunk = self.s.recv(1)
            if not chunk:
                raise ConnectionError('Empty websocket handshake')
            header.extend(chunk)
        accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        if b' 101 ' not in header.split(b'\r\n')[0] or accept.encode() not in header:
            self.s.close()
            raise ConnectionError('Public reference feed unavailable')

    def send(self, data, opcode=1):
        data = data.encode() if isinstance(data, str) else data
        n = len(data)
        prefix = bytes([0x80 | opcode, 0x80 | n]) if n < 126 else bytes([0x80 | opcode, 0xfe]) + struct.pack('!H', n)
        mask = os.urandom(4)
        self.s.sendall(prefix + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def read(self, n):
        data = b''
        while len(data) < n:
            part = self.s.recv(n - len(data))
            if not part:
                raise ConnectionError('Reference feed disconnected')
            data += part
        return data

    def receive(self):
        a, b = self.read(2)
        n = b & 127
        if n == 126:
            n = struct.unpack('!H', self.read(2))[0]
        elif n == 127:
            n = struct.unpack('!Q', self.read(8))[0]
        if n > 1048576 or b & 128 or not a & 128:
            raise ConnectionError('Unsupported reference frame')
        body = self.read(n)
        if a & 15 == 8:
            raise ConnectionError('Reference feed closed')
        if a & 15 == 9:
            self.send(body, 10)
            return None
        return body.decode() if a & 15 == 1 else None

    def close(self):
        self.s.close()

