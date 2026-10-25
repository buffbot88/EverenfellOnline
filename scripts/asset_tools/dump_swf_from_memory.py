"""Dump decoded SWF modules from a running Flash projector's memory (read-only).

The loader decodes packed UI modules into RAM before consuming them. This
scans the process's committed, readable memory for SWF headers
(FWS/CWS/ZWS), keeps only candidates whose declared length and version are
plausible, and writes each one to the output folder with its sha256.

Read-only: uses ReadProcessMemory, never writes to the target process.
Windows-only (ctypes). Usage:
  python dump_swf_from_memory.py --pid 18196 --out output/swf-memory
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import json
import os
import struct
import sys

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100
SIGS = (b'FWS', b'CWS', b'ZWS')
MIN_LEN = 64
MAX_LEN = 64 * 1024 * 1024


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ('BaseAddress', ctypes.c_void_p),
        ('AllocationBase', ctypes.c_void_p),
        ('AllocationProtect', wt.DWORD),
        ('RegionSize', ctypes.c_size_t),
        ('State', wt.DWORD),
        ('Protect', wt.DWORD),
        ('Type', wt.DWORD),
    ]


kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p,
                                    ctypes.POINTER(MEMORY_BASIC_INFORMATION),
                                    ctypes.c_size_t]
kernel32.VirtualQueryEx.restype = ctypes.c_size_t
kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                       ctypes.c_size_t,
                                       ctypes.POINTER(ctypes.c_size_t)]
kernel32.ReadProcessMemory.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]


def readable(protect):
    return bool(protect) and not (protect & (PAGE_NOACCESS | PAGE_GUARD))


def read_region(h, addr, size):
    buf = ctypes.create_string_buffer(size)
    got = ctypes.c_size_t(0)
    ok = kernel32.ReadProcessMemory(h, ctypes.c_void_p(addr), buf, size,
                                    ctypes.byref(got))
    return buf.raw[:got.value] if ok else None


def swf_candidate(buf, off):
    """Validate a SWF header at buf[off:]. Return the declared length or None."""
    if off + 8 > len(buf):
        return None
    sig = buf[off:off + 3]
    if sig not in SIGS:
        return None
    version = buf[off + 3]
    if not (1 <= version <= 60):
        return None
    (declared,) = struct.unpack('<I', buf[off + 4:off + 8])
    if not (MIN_LEN <= declared <= MAX_LEN):
        return None
    if sig == b'FWS' and off + declared > len(buf) and declared > len(buf) - off:
        # Uncompressed SWF whose declared length exceeds this region: take what exists.
        return len(buf) - off
    return declared


def scan(pid, out_dir, limit):
    h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        raise SystemExit('OpenProcess failed (error %d)' % ctypes.get_last_error())
    os.makedirs(out_dir, exist_ok=True)
    found = []
    seen = set()
    addr = 0
    mbi = MEMORY_BASIC_INFORMATION()
    try:
        while addr < 0x7FFFFFFFFFFF and len(found) < limit:
            n = kernel32.VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi),
                                        ctypes.sizeof(mbi))
            if not n:
                break
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize
            if mbi.State == MEM_COMMIT and readable(mbi.Protect) and size:
                buf = read_region(h, base, size)
                if buf:
                    i = 0
                    while True:
                        i = _next(buf, i)
                        if i < 0:
                            break
                        declared = swf_candidate(buf, i)
                        if declared:
                            data = buf[i:i + declared]
                            digest = hashlib.sha256(data).hexdigest()
                            if digest not in seen:
                                seen.add(digest)
                                name = 'mem-%012x-%s.swf' % (base + i, digest[:12])
                                with open(os.path.join(out_dir, name), 'wb') as fh:
                                    fh.write(data)
                                found.append({'name': name, 'address': hex(base + i),
                                              'signature': data[:3].decode('latin1'),
                                              'version': data[3], 'declared': declared,
                                              'size': len(data), 'sha256': digest})
                                if len(found) >= limit:
                                    break
                            i += 8
                        else:
                            i += 1
            nxt = base + size
            if nxt <= addr:
                break
            addr = nxt
    finally:
        kernel32.CloseHandle(h)
    with open(os.path.join(out_dir, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump({'pid': pid, 'candidates': found}, fh, indent=1)
    return found


def _next(buf, start):
    best = -1
    for sig in SIGS:
        j = buf.find(sig, start)
        if j >= 0 and (best < 0 or j < best):
            best = j
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pid', type=int, required=True)
    ap.add_argument('--out', default=os.path.join('output', 'swf-memory'))
    ap.add_argument('--limit', type=int, default=5000)
    args = ap.parse_args()
    found = scan(args.pid, args.out, args.limit)
    print('candidates=%d out=%s' % (len(found), args.out))


if __name__ == '__main__':
    sys.exit(main())
