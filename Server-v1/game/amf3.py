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


class XmlText(str):
    """AMF3 XML text, kept distinct from a plain string value."""


class Dictionary(list):
    """AMF3 dictionary: an ordered list of (key, value) pairs."""


class Obj(dict):
    """Dict that encodes as an AMF3 anonymous dynamic object (0x0A).

    Plain dicts encode as assoc arrays, so this marker type is what forces
    object encoding. Needed because the legacy server sent real objects in
    the login result (InOutput.success passes `this` and TimeZone.getDefault()
    through as objects), and the client reads properties off them:
    com.tian.net.socket::ServerInfoVO/decode() requires `.rawOffset`.
    """


class SealedObj(Obj):
    """Dict encoding as an AMF3 sealed-traits object (0x0A), like BlazeDS beans.

    Carries a class name plus an ordered sealed member list; values come
    from the dict in member order with no dynamic tail, and repeats use
    traits references. The Java server sends these (ZoneInfo, mall rows).
    """

    def __init__(self, values, cname='', members=()):
        super().__init__(values)
        self.cname = cname
        self.members = list(members)


class Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0
        self.strings = []
        self.objects = []
        self.traits = []

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
        if marker == 0x08:
            return self.date()
        if marker == 0x00:
            return None  # undefined reads as null for our purposes
        if marker in (0x0D, 0x0E, 0x0F, 0x10):
            return self.vector(marker)
        if marker == 0x11:
            return self.dictionary()
        if marker in (0x07, 0x0B):
            return self.xml()
        raise Amf3Error(f'unsupported marker 0x{marker:02x} at {self.p - 1}')

    def date(self):
        """AMF3 Date: a U29 ref followed by big-endian milliseconds (double).

        Needed for the legacy config tables (MapLine.dat et al), which embed
        dates; the login frames never use the marker.
        """
        ref = self.u29()
        if not ref & 1:
            return self.objects[ref >> 1]
        ms = struct.unpack('>d', self.d[self.p:self.p + 8])[0]
        self.p += 8
        self.objects.append(ms)
        return ms

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
        """Object: bit0 = not an object ref; bit1 = inline traits (else a traits ref).

        A traits reference carries its index in the upper bits and points at the
        traits table, which is separate from the object table. Ignoring that was
        the desync that stopped the legacy config tables.
        """
        header = self.u29()
        if not header & 1:
            return self.objects[header >> 1]
        if header & 0x02:
            cname = self.string()  # class name ('' = anonymous)
            sealed = header >> 4
            members = [self.string() for _ in range(sealed)]
            traits = (cname, members, bool(header & 0x04), bool(header & 0x08))
            self.traits.append(traits)
        else:
            traits = self.traits[header >> 2]
        _cname, members, externalizable, dynamic = traits
        if externalizable:
            raise Amf3Error('externalizable objects unsupported')
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

    def vector(self, marker):
        """Typed vectors 0x0D (int), 0x0E (uint), 0x0F (double), 0x10 (object)."""
        header = self.u29()
        if not header & 1:
            return self.objects[header >> 1]
        count = header >> 1
        self.u8()  # fixed-length flag; always present, not needed to decode
        if marker == 0x10:
            self.string()  # element class name ('' = any)
            items = []
            self.objects.append(items)
            items.extend(self.read() for _ in range(count))
            return items
        if marker == 0x0F:
            items = [struct.unpack('>d', self.d[self.p + 8 * i:self.p + 8 * i + 8])[0]
                     for i in range(count)]
            self.p += 8 * count
        else:
            fmt = '>i' if marker == 0x0D else '>I'
            items = [struct.unpack(fmt, self.d[self.p + 4 * i:self.p + 4 * i + 4])[0]
                     for i in range(count)]
            self.p += 4 * count
        self.objects.append(items)
        return items

    def dictionary(self):
        """Dictionary 0x11: a list of (key, value) pairs; keys may be any type."""
        header = self.u29()
        if not header & 1:
            return self.objects[header >> 1]
        self.u8()  # weak-keys flag
        pairs = Dictionary()
        self.objects.append(pairs)
        for _ in range(header >> 1):
            key = self.read()
            pairs.append((key, self.read()))
        return pairs

    def xml(self):
        """XML 0x07 / XML-doc 0x0B: a U29 length and UTF-8 text, referenced by the object table."""
        header = self.u29()
        if not header & 1:
            return self.objects[header >> 1]
        text = XmlText(self.utf(header >> 1))
        self.objects.append(text)
        return text

    def array(self):
        ref = self.u29()
        if not ref & 1:
            return self.objects[ref >> 1]
        dense = ref >> 1
        # Reserve the reference slot first; the shape is finalized once the
        # assoc entries show whether this is a dense list or an ECMA array.
        value = []
        self.objects.append(value)
        assoc = {}
        while True:
            k = self.string()
            if k == '':
                break
            assoc[k] = self.read()
        items = [self.read() for _ in range(dense)]
        if not assoc:
            value.extend(items)
            return value
        # Back-references issued during the child reads above still point at
        # the reserved list; cyclic keyed arrays do not occur in this traffic.
        return {'__assoc__': assoc, 'items': items}


class Writer:
    def __init__(self):
        self.b = bytearray()
        self.strings = []
        self.traits = []

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
        elif isinstance(v, SealedObj):
            self.b.append(0x0A)
            key = (v.cname, tuple(v.members))
            if key in self.traits:
                self.u29((self.traits.index(key) << 2) | 0x01)
            else:
                self.traits.append(key)
                # traits word: (sealedCount << 4) | 0x03 (dynamic bit clear).
                self.u29((len(v.members) << 4) | 0x03)
                self.string(v.cname)
                for k in v.members:
                    self.string(str(k))
            # Sealed values always travel inline; only the traits are shared.
            for k in v.members:
                self.write(v[k])
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
