#include <pybind11/pybind11.h>
#include <pybind11/stl.h> // Behövs för att hantera Python-listor automatiskt
#include <string>
#include <vector>

// this is a C++ variant of /chucnyserver/pb.py
// it is like 20-100x faster than the clunky python version. it's pretty much only this that has to be written in C++ actually



// this is just a test and an ai slop with C++. Don't worry about the code being written in swedish

namespace py = pybind11;

// Blixtsnabb varint-kodning på maskinnivå
std::string varint(uint64_t n) {
    std::string out;
    while (true) {
        uint8_t b = n & 0x7F;
        n >>= 7;
        if (n) {
            out.push_back(b | 0x80);
        } else {
            out.push_back(b);
            return out;
        }
    }
}

class Writer {
public:
    std::string buf;

    // Hjälpfunktion för att skriva taggar
    void tag(int field, int wire) {
        buf += varint((field << 3) | wire);
    }

    // .uint() och .int_() använder WT_VARINT (0)
    Writer& uint(int field, uint64_t value) {
        tag(field, 0);
        buf += varint(value);
        return *this;
    }

    Writer& int_(int field, int64_t value) {
        tag(field, 0);
        // Hanterar negativa tal via tvåkomplement (64-bit) precis som din Python-kod
        buf += varint(static_cast<uint64_t>(value));
        return *this;
    }

    // .bool_()
    Writer& bool_(int field, bool value) {
        return uint(field, value ? 1 : 0);
    }

    // .bytes() och .string() och .message() använder WT_LEN (2)
    Writer& bytes(int field, const std::string& value) {
        tag(field, 2);
        buf += varint(value.size()) + value;
        return *this;
    }

    Writer& string(int field, const std::string& value) {
        return bytes(field, value);
    }

    Writer& message(int field, const std::string& sub_bytes) {
        return bytes(field, sub_bytes);
    }

    // .packed_varints() tar en lista/vektor med tal
    Writer& packed_varints(int field, const std::vector<uint64_t>& values) {
        std::string body;
        for (uint64_t v : values) {
            body += varint(v);
        }
        return bytes(field, body);
    }

    // .to_bytes() skickar tillbaka råa bytes till Python
    py::bytes to_bytes() {
        return py::bytes(buf);
    }
};

// Skapa Python-modulen
PYBIND11_MODULE(pogo_proto, m) {
    py::class_<Writer>(m, "Writer")
        .def(py::init<>())
        .def("uint", &Writer::uint)
        .def("int_", &Writer::int_)
        .def("bool_", &Writer::bool_)
        .def("string", &Writer::string)
        .def("message", &Writer::message)
        .def("packed_varints", &Writer::packed_varints)
        .def("to_bytes", &Writer::to_bytes);
}
