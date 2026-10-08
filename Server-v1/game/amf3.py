"""Minimal AMF3 codec (BlazeDS-compatible subset) for the game protocol.

Covers what the login handshake actually uses: null/bool/int/double/string
and dense arrays. Object markers beyond this raise, loudly, rather than
mis-decoding. String tables are per-message (decoder resets per frame, as
AmfRequestDecoder calls Amf3Input.reset() before each readObject).
"""
import struct

INT_MIN, INT_MAX = -(1 << 28), (1 << 28) - 1


class Amf3Error(ValueError):
    pass


class ByteArray(bytes):
    """AMF3 inline ByteArray payload, distinct from strings and arrays."""


class Obj(dict):
    """Dict that encodes as an AMF3 anonymous dynamic object (0x0A).

    Plain dicts encode as assoc arrays, so this marker type is what forces
    object encoding. Needed because the legacy server sent real objects in
    the login result (InOutput.success passes `this` and TimeZone.getDefault()
    through as objects), and the client reads properties off them:
    com.tian.net.socket::ServerInfoVO/decode() requires `.rawOffset`.
    """


class Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0
        self.strings = []
        self.objects = []

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u29(self):
        v = 0
        for _ in range(4):
            b = self.u8()
            if _ < 3:
                v = (v << 7) | (b & 0x7F)
                if not b & 0x80:
                    return v
            else:
                v = (v << 8) | b
                return v
        raise Amf3Error('bad u29')

    def utf(self, n):
        s = self.d[self.p:self.p + n].decode('utf-8')
        self.p += n
        return s

    def string(self):
        ref = self.u29()
        if not ref & 1:
            return self.strings[ref >> 1]
        ln = ref >> 1
        s = self.utf(ln) if ln else ''
        if s:
            self.strings.append(s)
        return s

    def read(self):
        marker = self.u8()
        if marker == 0x01:
            return None
        if marker == 0x02:
            return False
        if marker == 0x03:
            return True
        if marker == 0x04:
            v = self.u29()
            return v - (1 << 29) if v & (1 << 28) else v
        if marker == 0x05:
            v = struct.unpack('>d', self.d[self.p:self.p + 8])[0]
            self.p += 8
            return v
        if marker == 0x06:
            return self.string()
        if marker == 0x09:
            return self.array()
        if marker == 0x0C:
            return self.byte_array()
        if marker == 0x0A:
            return self.object()
        raise Amf3Error(f'unsupported marker 0x{marker:02x} at {self.p - 1}')

    def byte_array(self):
        header = self.u29()
        if not header & 1:
            return self.objects[header >> 1]
        size = header >> 1
        value = ByteArray(self.d[self.p:self.p + size])
        if self.p + size > len(self.d):
            raise Amf3Error('truncated ByteArray')
        self.p += size
        self.objects.append(value)
        return value

    def object(self):
        traits = self.u29()
        if not traits & 1:
            return self.objects[traits >> 1]
        flags = traits & 0x0F
        sealed = traits >> 4
        self.string()  # class name (empty = anonymous)
        if flags & 0x04:
            raise Amf3Error('externalizable objects unsupported')
        dynamic = bool(flags & 0x08)
        members = [self.string() for _ in range(sealed)]
        obj = Obj()
        self.objects.append(obj)
        for m in members:
            obj[m] = self.read()
        if dynamic:
            while True:
                k = self.string()
                if k == '':
                    break
                obj[k] = self.read()
        return obj

    def array(self):
        ref = self.u29()
        if not ref & 1:
            return self.objects[ref >> 1]
        dense = ref >> 1
        assoc = {}
        value = {'__assoc__': assoc, 'items': []} if assoc else []
        self.objects.append(value)
        while True:
            k = self.string()
            if k == '':
                break
            assoc[k] = self.read()
        items = [self.read() for _ in range(dense)]
        if assoc:
            value['items'] = items
            return value
        value.extend(items)
        return value


class Writer:
    def __init__(self):
        self.b = bytearray()
        self.strings = []

    def u29(self, v):
        v &= 0x1FFFFFFF
        if v < 0x80:
            self.b.append(v)
        elif v < 0x4000:
            self.b += bytes([(v >> 7) | 0x80, v & 0x7F])
        elif v < 0x200000:
            self.b += bytes([(v >> 14) | 0x80, ((v >> 7) & 0x7F) | 0x80, v & 0x7F])
        else:
            self.b += bytes([(v >> 22) | 0x80, ((v >> 15) & 0x7F) | 0x80,
                             ((v >> 8) & 0x7F) | 0x80, v & 0xFF])

    def string(self, s):
        if s == '':
            self.u29(1)
            return
        if s in self.strings:
            self.u29(self.strings.index(s) << 1)
            return
        self.strings.append(s)
        enc = s.encode('utf-8')
        self.u29((len(enc) << 1) | 1)
        self.b += enc

    def write(self, v):
        if v is None:
            self.b.append(0x01)
        elif v is True or v is False:
            self.b.append(0x03 if v else 0x02)
        elif isinstance(v, int):
            if INT_MIN <= v <= INT_MAX:
                self.b.append(0x04)
                self.u29(v)
            else:
                self.b.append(0x05)
                self.b += struct.pack('>d', float(v))
        elif isinstance(v, float):
            self.b.append(0x05)
            self.b += struct.pack('>d', v)
        elif isinstance(v, str):
            self.b.append(0x06)
            self.string(v)
        elif isinstance(v, (ByteArray, bytes, bytearray, memoryview)):
            raw = bytes(v)
            self.b.append(0x0C)
            self.u29((len(raw) << 1) | 1)
            self.b += raw
        elif isinstance(v, (list, tuple)):
            self.b.append(0x09)
            items = list(v)
            self.u29((len(items) << 1) | 1)
            self.u29(1)  # empty assoc terminator
            for it in items:
                self.write(it)
        elif isinstance(v, Obj):
            self.b.append(0x0A)
            # traits word: (sealedMemberCount << 4) | dynamic(0x08) | 0x03.
            # 0x0B is the canonical anonymous-dynamic value BlazeDS writes;
            # sealed objects use (count << 4) | 0x03 (e.g. 0x23 for 2 members).
            self.u29(0x0B)
            self.u29(1)  # empty class name -> anonymous
            for k, val in v.items():
                self.string(str(k))
                self.write(val)
            self.u29(1)  # empty-string terminator ends the dynamic members
        elif isinstance(v, dict):
            # assoc array: only used if ever needed for exotic fields
            self.b.append(0x09)
            self.u29(1)  # dense 0, inline
            for k, val in v.items():
                self.string(str(k))
                self.write(val)
            self.u29(1)
        else:
            raise Amf3Error(f'cannot encode {type(v)}')


def decode(data: bytes):
    r = Reader(data)
    v = r.read()
    if r.p != len(data):
        raise Amf3Error(f'trailing bytes: {len(data) - r.p}')
    return v


def encode(value) -> bytes:
    w = Writer()
    w.write(value)
    return bytes(w.b)
