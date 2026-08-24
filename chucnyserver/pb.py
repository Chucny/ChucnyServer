"""
Minimal protobuf wire-format codec for the PoGO 0.29 private server.

We deliberately avoid .proto files / protoc. Protobuf's wire format is simple
and we only need a handful of messages. Just as important: the generic decoder
(`decode`/`pretty`) lets us LOG the exact field layout the real 0.29 client
sends, so we verify field numbers against reality instead of trusting memory.

Wire types:
    0 varint        (int32/int64/uint/bool/enum)
    1 64-bit        (fixed64/double)
    2 length-delim  (string/bytes/embedded message/packed repeated)
    5 32-bit        (fixed32/float)
"""
import struct

WT_VARINT, WT_64, WT_LEN, WT_32 = 0, 1, 2, 5


# ---------------------------------------------------------------- encoding ---
def varint(n: int) -> bytes:
    if n < 0:                       # two's complement, 64-bit (for sint use zigzag elsewhere)
        n &= (1 << 64) - 1
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return varint((field << 3) | wire)


class Writer:
    """Builds a protobuf message body byte-by-byte, in field order."""

    def __init__(self):
        self.buf = bytearray()

    def raw(self, b: bytes):
        self.buf += b
        return self

    def uint(self, field: int, value: int):
        self.buf += _tag(field, WT_VARINT) + varint(value)
        return self

    int_ = uint            # int32/int64 (non-negative here) share encoding
    enum = uint
    def bool_(self, field: int, value: bool):
        return self.uint(field, 1 if value else 0)

    def double(self, field: int, value: float):
        self.buf += _tag(field, WT_64) + struct.pack("<d", value)
        return self

    def fixed64(self, field: int, value: int):
        self.buf += _tag(field, WT_64) + struct.pack("<Q", value & ((1 << 64) - 1))
        return self

    def fixed32(self, field: int, value: int):
        self.buf += _tag(field, WT_32) + struct.pack("<I", value & 0xFFFFFFFF)
        return self

    def float_(self, field: int, value: float):
        self.buf += _tag(field, WT_32) + struct.pack("<f", value)
        return self

    def bytes_(self, field: int, value: bytes):
        self.buf += _tag(field, WT_LEN) + varint(len(value)) + value
        return self

    def string(self, field: int, value: str):
        return self.bytes_(field, value.encode("utf-8"))

    def message(self, field: int, sub: "Writer | bytes"):
        body = sub.to_bytes() if isinstance(sub, Writer) else sub
        return self.bytes_(field, body)

    def packed_varints(self, field: int, values) -> "Writer":
        body = b"".join(varint(v) for v in values)
        return self.bytes_(field, body)

    def packed_floats(self, field: int, values) -> "Writer":
        body = b"".join(struct.pack("<f", float(v)) for v in values)
        return self.bytes_(field, body)

    def to_bytes(self) -> bytes:
        return bytes(self.buf)


# ---------------------------------------------------------------- decoding ---
def _read_varint(buf, pos):
    shift = result = 0
    while True:
        b = buf[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


def decode(buf: bytes):
    """Generic decode -> list of dicts {field, wire, value}. Never raises on
    unknown structure; embedded messages are returned as raw bytes."""
    pos, out = 0, []
    n = len(buf)
    while pos < n:
        key, pos = _read_varint(buf, pos)
        field, wire = key >> 3, key & 7
        if wire == WT_VARINT:
            val, pos = _read_varint(buf, pos)
        elif wire == WT_64:
            val = struct.unpack_from("<Q", buf, pos)[0]; pos += 8
        elif wire == WT_LEN:
            ln, pos = _read_varint(buf, pos)
            val = bytes(buf[pos:pos + ln]); pos += ln
        elif wire == WT_32:
            val = struct.unpack_from("<I", buf, pos)[0]; pos += 4
        else:
            break  # unknown / group, bail
        out.append({"field": field, "wire": wire, "value": val})
    return out


def get(fields, field_no, wire=None):
    """First value for a field number (optionally filtered by wire type)."""
    for f in fields:
        if f["field"] == field_no and (wire is None or f["wire"] == wire):
            return f["value"]
    return None


def get_all(fields, field_no):
    return [f["value"] for f in fields if f["field"] == field_no]


def pretty(buf: bytes, indent=0, max_depth=4):
    """Human-readable recursive dump — used to inspect real client requests."""
    pad = "  " * indent
    lines = []
    for f in decode(buf):
        fld, wire, val = f["field"], f["wire"], f["value"]
        if wire == WT_LEN and isinstance(val, bytes):
            # try to interpret as nested message, else show string/hex
            looks_msg = max_depth > 0 and len(val) > 0 and _looks_like_message(val)
            if looks_msg:
                lines.append(f"{pad}#{fld} (len {len(val)}) {{")
                lines.append(pretty(val, indent + 1, max_depth - 1))
                lines.append(f"{pad}}}")
            else:
                try:
                    s = val.decode("utf-8")
                    printable = all(31 < ord(c) < 127 or c in "\t\n" for c in s)
                except UnicodeDecodeError:
                    printable = False
                if printable and val:
                    lines.append(f'{pad}#{fld} str="{s}"')
                else:
                    lines.append(f"{pad}#{fld} bytes[{len(val)}]={val[:32].hex()}"
                                 + ("..." if len(val) > 32 else ""))
        elif wire == WT_64:
            d = struct.unpack("<d", struct.pack("<Q", val))[0]
            lines.append(f"{pad}#{fld} fixed64={val} (double~{d:.6g})")
        elif wire == WT_32:
            lines.append(f"{pad}#{fld} fixed32={val}")
        else:
            lines.append(f"{pad}#{fld} varint={val}")
    return "\n".join(lines)


def _looks_like_message(buf: bytes) -> bool:
    """Heuristic: can we cleanly walk the whole buffer as protobuf records?"""
    try:
        pos, n = 0, len(buf)
        while pos < n:
            key, pos = _read_varint(buf, pos)
            wire = key & 7
            if wire == WT_VARINT:
                _, pos = _read_varint(buf, pos)
            elif wire == WT_64:
                pos += 8
            elif wire == WT_LEN:
                ln, pos = _read_varint(buf, pos); pos += ln
            elif wire == WT_32:
                pos += 4
            else:
                return False
        return pos == n
    except (IndexError, Exception):
        return False
