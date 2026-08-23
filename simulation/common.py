import base64, json

def send_json(sock, obj):
    sock.sendall((json.dumps(obj, separators=(",", ":")) + "\n").encode())

def recv_lines(sock, buffer=b""):
    data = sock.recv(65536)
    if not data:
        return [], buffer, False
    buffer += data
    out = []
    while b"\n" in buffer:
        line, buffer = buffer.split(b"\n", 1)
        if line:
            out.append(json.loads(line.decode()))
    return out, buffer, True

def b64e(data):
    return base64.b64encode(data).decode()

def b64d(text):
    return base64.b64decode(text.encode())
