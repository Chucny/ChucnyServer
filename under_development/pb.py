"""
Minimal protobuf wire-format codec wrapper over the Go `pb` implementation.
"""
import _pb

WT_VARINT, WT_64, WT_LEN, WT_32 = 0, 1, 2, 5

def varint(n: int) -> bytes:
    return bytes(_pb.Varint(n))

class Writer:
    """Builds a protobuf message body byte-by-byte, using the Go backend."""

    def __init__(self):
        self._go_writer = _pb.NewWriter()

    def raw(self, b: bytes):
        self._go_writer.Raw(b)
        return self

    def uint(self, field: int, value: int):
        self._go_writer.Uint(field, value)
        return self

    def int_(self, field: int, value: int):
        return self.uint(field, value)

    def enum(self, field: int, value: int):
        return self.uint(field, value)

    def bool_(self, field: int, value: bool):
        self._go_writer.Bool(field, value)
        return self

    def double(self, field: int, value: float):
        self._go_writer.Double(field, value)
        return self

    def fixed64(self, field: int, value: int):
        self._go_writer.Fixed64(field, value)
        return self

    def fixed32(self, field: int, value: int):
        self._go_writer.Fixed32(field, value)
        return self

    def float_(self, field: int, value: float):
        self._go_writer.Float(field, value)
        return self

    def bytes_(self, field: int, value: bytes):
        self._go_writer.Bytes(field, value)
        return self

    def string(self, field: int, value: str):
        self._go_writer.String(field, value)
        return self

    def message(self, field: int, sub):
        body = sub.to_bytes() if isinstance(sub, Writer) else sub
        self.bytes_(field, body)
        return self

    def packed_varints(self, field: int, values):
        self._go_writer.PackedVarints(field, values)
        return self

    def packed_floats(self, field: int, values):
        self._go_writer.PackedFloats(field, values)
        return self

    def to_bytes(self) -> bytes:
        return bytes(self._go_writer.ToBytes())


def decode(buf: bytes):
    """Generic decode -> list of dicts {field, wire, value}."""
    records = _pb.Decode(buf)
    out = []
    for r in records:
        out.append({
            "field": r.Field,
            "wire": r.Wire,
            "value": bytes(r.Value) if isinstance(r.Value, _pb.GoSlice) else r.Value
        })
    return out


def get(fields, field_no, wire=None):
    """First value for a field number (optionally filtered by wire type)."""
    wire_arg = -1 if wire is None else wire
    for f in fields:
        if f["field"] == field_no and (wire is None or f["wire"] == wire):
            return f["value"]
    return None


def get_all(fields, field_no):
    """Returns all values matching field_no."""
    return [f["value"] for f in fields if f["field"] == field_no]


def pretty(buf: bytes, indent: int = 0, max_depth: int = 4) -> str:
    """Human-readable recursive dump via Go backend."""
    return _pb.Pretty(buf, indent, max_depth)
