"""SimpleEncrypt: byte stream cipher from com/kernel/encrypt/SimpleEncrypt.

Recovered from JVM bytecode (see tools/javap.py), not copied source:
  encode: data[i] = (data[i] + ticket[ticketIndex++ % ticketLen]
                                - key[keyIndex++ % keyLen]) mod 256
  decode: data[i] = (data[i] - ticket[deTicketIndex++ % ticketLen]
                                + key[deKeyIndex++ % keyLen]) mod 256
Indices wrap independently per direction (encode vs decode counters).

Session setup (AmfRequestDecoder.initEncrypt): key = random UUID string,
ticket = 'NITABAHAIZHENGEINIPOLE'; the key bytes are sent to the client
in the clear (u32be-prefixed) right after the INITKEY frame.
"""
import uuid

TICKET = 'NITABAHAIZHENGEINIPOLE'


def new_key():
    return str(uuid.uuid4())


class SimpleEncrypt:
    def __init__(self, key, ticket=TICKET):
        if not key:
            raise ValueError('key must be not null or empty.')
        if not ticket:
            raise ValueError('ticket must be not null or empty.')
        self.ticket = ticket.encode('utf-8')
        self.key = key.encode('utf-8')
        self.ticket_index = 0
        self.key_index = 0
        self.de_ticket_index = 0
        self.de_key_index = 0

    def encode(self, data: bytes) -> bytes:
        out = bytearray(data)
        for i in range(len(out)):
            tk = self.ticket[self.ticket_index % len(self.ticket)]
            self.ticket_index += 1
            kv = self.key[self.key_index % len(self.key)]
            self.key_index += 1
            out[i] = (out[i] + tk - kv) & 0xFF
        return bytes(out)

    def decode(self, data: bytes) -> bytes:
        out = bytearray(data)
        for i in range(len(out)):
            tk = self.ticket[self.de_ticket_index % len(self.ticket)]
            self.de_ticket_index += 1
            kv = self.key[self.de_key_index % len(self.key)]
            self.de_key_index += 1
            out[i] = (out[i] - tk + kv) & 0xFF
        return bytes(out)
