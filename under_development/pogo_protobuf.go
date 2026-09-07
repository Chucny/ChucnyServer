// don't worry, this is a random ai slop test

package pb

import (
	"bytes"
	"encoding/binary"
	"fmt"
	"math"
	"strings"
)

const (
	WtVarint = 0
	Wt64     = 1
	WtLen    = 2
	Wt32     = 5
)

type Record struct {
	Field int
	Wire  int
	Value interface{}
}

func Varint(n int64) []byte {
	u := uint64(n)
	var out []byte
	for {
		b := byte(u & 0x7F)
		u >>= 7
		if u != 0 {
			out = append(out, b|0x80)
		} else {
			out = append(out, b)
			return out
		}
	}
}

func Tag(field, wire int) []byte {
	return Varint(int64((field << 3) | wire))
}

type Writer struct {
	buf bytes.Buffer
}

func NewWriter() *Writer {
	return &Writer{}
}

func (w *Writer) Raw(b []byte) *Writer {
	w.buf.Write(b)
	return w
}

func (w *Writer) Uint(field int, value uint64) *Writer {
	w.buf.Write(Tag(field, WtVarint))
	w.buf.Write(Varint(int64(value)))
	return w
}

func (w *Writer) Int(field int, value int64) *Writer {
	return w.Uint(field, uint64(value))
}

func (w *Writer) Enum(field int, value int64) *Writer {
	return w.Uint(field, uint64(value))
}

func (w *Writer) Bool(field int, value bool) *Writer {
	val := uint64(0)
	if value {
		val = 1
	}
	return w.Uint(field, val)
}

func (w *Writer) Double(field int, value float64) *Writer {
	w.buf.Write(Tag(field, Wt64))
	bits := math.Float64bits(value)
	b := make([]byte, 8)
	binary.LittleEndian.PutUint64(b, bits)
	w.buf.Write(b)
	return w
}

func (w *Writer) Fixed64(field int, value uint64) *Writer {
	w.buf.Write(Tag(field, Wt64))
	b := make([]byte, 8)
	binary.LittleEndian.PutUint64(b, value)
	w.buf.Write(b)
	return w
}

func (w *Writer) Fixed32(field int, value uint32) *Writer {
	w.buf.Write(Tag(field, Wt32))
	b := make([]byte, 4)
	binary.LittleEndian.PutUint32(b, value)
	w.buf.Write(b)
	return w
}

func (w *Writer) Float(field int, value float32) *Writer {
	w.buf.Write(Tag(field, Wt32))
	bits := math.Float32bits(value)
	b := make([]byte, 4)
	binary.LittleEndian.PutUint32(b, bits)
	w.buf.Write(b)
	return w
}

func (w *Writer) Bytes(field int, value []byte) *Writer {
	w.buf.Write(Tag(field, WtLen))
	w.buf.Write(Varint(int64(len(value))))
	w.buf.Write(value)
	return w
}

func (w *Writer) String(field int, value string) *Writer {
	return w.Bytes(field, []byte(value))
}

func (w *Writer) PackedVarints(field int, values []int64) *Writer {
	var body bytes.Buffer
	for _, v := range values {
		body.Write(Varint(v))
	}
	return w.Bytes(field, body.Bytes())
}

func (w *Writer) PackedFloats(field int, values []float32) *Writer {
	var body bytes.Buffer
	for _, v := range values {
		bits := math.Float32bits(v)
		b := make([]byte, 4)
		binary.LittleEndian.PutUint32(b, bits)
		body.Write(b)
	}
	return w.Bytes(field, body.Bytes())
}

func (w *Writer) ToBytes() []byte {
	return w.buf.Bytes()
}

func ReadVarint(buf []byte, pos int) (uint64, int, error) {
	var result uint64
	var shift uint
	for {
		if pos >= len(buf) {
			return 0, pos, fmt.Errorf("unexpected EOF")
		}
		b := buf[pos]
		pos++
		result |= uint64(b&0x7F) << shift
		if (b & 0x80) == 0 {
			return result, pos, nil
		}
		shift += 7
	}
}

func Decode(buf []byte) []Record {
	pos, n := 0, len(buf)
	var out []Record

	for pos < n {
		key, newPos, err := ReadVarint(buf, pos)
		if err != nil {
			break
		}
		pos = newPos

		field := int(key >> 3)
		wire := int(key & 7)
		var val interface{}

		if wire == WtVarint {
			var v uint64
			v, pos, err = ReadVarint(buf, pos)
			if err != nil {
				break
			}
			val = v
		} else if wire == Wt64 {
			if pos+8 > n {
				break
			}
			val = binary.LittleEndian.Uint64(buf[pos : pos+8])
			pos += 8
		} else if wire == WtLen {
			var ln uint64
			ln, pos, err = ReadVarint(buf, pos)
			if err != nil || pos+int(ln) > n {
				break
			}
			val = append([]byte(nil), buf[pos:pos+int(ln)]...)
			pos += int(ln)
		} else if wire == Wt32 {
			if pos+4 > n {
				break
			}
			val = binary.LittleEndian.Uint32(buf[pos : pos+4])
			pos += 4
		} else {
			break
		}

		out = append(out, Record{Field: field, Wire: wire, Value: val})
	}
	return out
}

func Get(fields []Record, fieldNo int, wire int) interface{} {
	for _, f := range fields {
		if f.Field == fieldNo && (wire < 0 || f.Wire == wire) {
			return f.Value
		}
	}
	return nil
}

func GetAll(fields []Record, fieldNo int) []interface{} {
	var res []interface{}
	for _, f := range fields {
		if f.Field == fieldNo {
			res = append(res, f.Value)
		}
	}
	return res
}

func Pretty(buf []byte, indent, maxDepth int) string {
	pad := strings.Repeat("  ", indent)
	var lines []string

	for _, f := range Decode(buf) {
		fld, wire, val := f.Field, f.Wire, f.Value

		if wire == WtLen {
			bVal, ok := val.([]byte)
			if ok {
				looksMsg := maxDepth > 0 && len(bVal) > 0 && LooksLikeMessage(bVal)
				if looksMsg {
					lines = append(lines, fmt.Sprintf("%s#%d (len %d) {", pad, fld, len(bVal)))
					lines = append(lines, Pretty(bVal, indent+1, maxDepth-1))
					lines = append(lines, fmt.Sprintf("%s}", pad))
				} else {
					printable := true
					s := string(bVal)
					if len(bVal) == 0 {
						printable = false
					}
					for _, r := range s {
						if !(r > 31 && r < 127) && r != '\t' && r != '\n' && r != '\r' {
							printable = false
							break
						}
					}
					if printable {
						lines = append(lines, fmt.Sprintf("%s#%d str=%q", pad, fld, s))
					} else {
						hexStr := fmt.Sprintf("%x", bVal)
						if len(bVal) > 32 {
							hexStr = fmt.Sprintf("%x...", bVal[:32])
						}
						lines = append(lines, fmt.Sprintf("%s#%d bytes[%d]=%s", pad, fld, len(bVal), hexStr))
					}
				}
			}
		} else if wire == Wt64 {
			uVal := val.(uint64)
			dVal := math.Float64frombits(uVal)
			lines = append(lines, fmt.Sprintf("%s#%d fixed64=%d (double~%.6g)", pad, fld, uVal, dVal))
		} else if wire == Wt32 {
			lines = append(lines, fmt.Sprintf("%s#%d fixed32=%d", pad, fld, val))
		} else {
			lines = append(lines, fmt.Sprintf("%s#%d varint=%d", pad, fld, val))
		}
	}
	return strings.Join(lines, "\n")
}

func LooksLikeMessage(buf []byte) bool {
	pos, n := 0, len(buf)
	for pos < n {
		key, newPos, err := ReadVarint(buf, pos)
		if err != nil {
			return false
		}
		pos = newPos
		wire := int(key & 7)

		if wire == WtVarint {
			_, pos, err = ReadVarint(buf, pos)
			if err != nil {
				return false
			}
		} else if wire == Wt64 {
			pos += 8
		} else if wire == WtLen {
			ln, newPos, err := ReadVarint(buf, pos)
			if err != nil {
				return false
			}
			pos = newPos + int(ln)
		} else if wire == Wt32 {
			pos += 4
		} else {
			return false
		}
	}
	return pos == n
}
