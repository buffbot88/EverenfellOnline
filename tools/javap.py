#!/usr/bin/env python3
"""Minimal JVM class-file disassembler for targeted reverse engineering.

Parses the constant pool, fields, methods and Code attributes, and prints a
readable bytecode listing with constant resolution. Supports the full
classic opcode set needed for 1.6-era classes (no invokedynamic).

Usage: python3 tools/javap.py <classfile|jar!inner> [--method name]
       python3 tools/javap.py file.jar com/xianling/Foo.class [--method bar]
"""
import struct
import sys
import zipfile

TAG = {7: 'Class', 9: 'Fieldref', 10: 'Methodref', 11: 'InterfaceMethodref',
       8: 'String', 3: 'Integer', 4: 'Float', 5: 'Long', 6: 'Double',
       12: 'NameAndType', 1: 'Utf8', 15: 'MethodHandle', 16: 'MethodType',
       18: 'InvokeDynamic'}


class Reader:
    def __init__(self, d):
        self.d = d
        self.p = 0

    def u1(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def u2(self):
        v = struct.unpack('>H', self.d[self.p:self.p + 2])[0]
        self.p += 2
        return v

    def u4(self):
        v = struct.unpack('>I', self.d[self.p:self.p + 4])[0]
        self.p += 4
        return v

    def s1(self):
        v = self.u1()
        return v - 256 if v > 127 else v

    def s2(self):
        v = self.u2()
        return v - 65536 if v > 32767 else v

    def s4(self):
        v = self.u4()
        return v - 2**32 if v > 2**31 - 1 else v

    def bytes(self, n):
        v = self.d[self.p:self.p + n]
        self.p += n
        return v


def parse_class(data):
    r = Reader(data)
    assert r.u4() == 0xCAFEBABE, 'bad magic'
    r.u2()
    r.u2()  # minor, major
    n = r.u2()
    cp = [None] * n
    i = 1
    while i < n:
        tag = r.u1()
        if tag == 1:
            ln = r.u2()
            cp[i] = ('Utf8', r.bytes(ln).decode('utf-8', errors='replace'))
        elif tag == 7:
            cp[i] = ('Class', r.u2())
        elif tag == 8:
            cp[i] = ('String', r.u2())
        elif tag in (9, 10, 11):
            cp[i] = (TAG[tag], r.u2(), r.u2())
        elif tag == 12:
            cp[i] = ('NameAndType', r.u2(), r.u2())
        elif tag == 3:
            cp[i] = ('Integer', r.s4())
        elif tag == 4:
            cp[i] = ('Float', struct.unpack('>f', r.bytes(4))[0])
        elif tag in (5, 6):
            hi, lo = r.u4(), r.u4()
            v = (hi << 32) | lo
            if tag == 5:
                cp[i] = ('Long', v - 2**64 if v > 2**63 - 1 else v)
            else:
                cp[i] = ('Double', struct.unpack('>d', struct.pack('>Q', v))[0])
            i += 1
            if i < n:
                cp[i] = None
        elif tag == 15:
            cp[i] = ('MethodHandle', r.u1(), r.u2())
        elif tag == 16:
            cp[i] = ('MethodType', r.u2())
        elif tag == 18:
            cp[i] = ('InvokeDynamic', r.u2(), r.u2())
        else:
            raise ValueError(f'unknown cp tag {tag} at {i}')
        i += 1
    r.u2()
    this = r.u2()
    r.u2()  # super

    def cp_str(idx):
        e = cp[idx]
        if e is None:
            return f'#{idx}=?'
        if e[0] == 'Utf8':
            return e[1]
        if e[0] == 'Class':
            return cp_str(e[1]).replace('/', '.')
        if e[0] == 'String':
            return repr(cp_str(e[1]))
        if e[0] in ('Fieldref', 'Methodref', 'InterfaceMethodref'):
            c = cp_str(e[1])
            nt = cp[e[2]]
            return f'{c}.{cp_str(nt[1])}:{cp_str(nt[2])}'
        if e[0] == 'NameAndType':
            return f'{cp_str(e[1])}:{cp_str(e[2])}'
        if e[0] in ('Integer', 'Long', 'Float', 'Double'):
            return repr(e[1])
        return f'{e}'

    # interfaces
    for _ in range(r.u2()):
        r.u2()
    # fields
    fields = []
    for _ in range(r.u2()):
        r.u2()
        name, desc = cp_str(r.u2()), cp_str(r.u2())
        attrs = {}
        for _ in range(r.u2()):
            an, al = cp_str(r.u2()), r.u4()
            if an == 'ConstantValue':
                attrs['const'] = cp_str(r.u2())
            else:
                r.bytes(al)
        fields.append((name, desc, attrs))
    # methods
    methods = []
    for _ in range(r.u2()):
        r.u2()
        name, desc = cp_str(r.u2()), cp_str(r.u2())
        code = None
        for _ in range(r.u2()):
            an, al = cp_str(r.u2()), r.u4()
            raw = r.bytes(al)
            if an == 'Code':
                cr = Reader(raw)
                cr.u2()
                cr.u2()  # max_stack, max_locals
                clen = cr.u4()
                code = cr.bytes(clen)
                cr.bytes(8 * cr.u2())  # exceptions
                for _ in range(cr.u2()):  # attributes
                    cr.u2()
                    cr.bytes(cr.u4())
        methods.append((name, desc, code))
    return cp_str(this), cp, cp_str, fields, methods


# opcode table: name, operand size (negative = variable)
OPS = {}
for _op, _nm in [
    (0, 'nop'), (1, 'aconst_null'), (2, 'iconst_m1'), (3, 'iconst_0'),
    (4, 'iconst_1'), (5, 'iconst_2'), (6, 'iconst_3'), (7, 'iconst_4'),
    (8, 'iconst_5'), (9, 'lconst_0'), (10, 'lconst_1'), (11, 'fconst_0'),
    (12, 'fconst_1'), (13, 'fconst_2'), (14, 'dconst_0'), (15, 'dconst_1'),
    (16, 'bipush'), (17, 'sipush'), (18, 'ldc'), (19, 'ldc_w'),
    (20, 'ldc2_w'), (21, 'iload'), (22, 'lload'), (23, 'fload'),
    (24, 'dload'), (25, 'aload'), (26, 'iload_0'), (27, 'iload_1'),
    (28, 'iload_2'), (29, 'iload_3'), (30, 'lload_0'), (31, 'lload_1'),
    (32, 'lload_2'), (33, 'lload_3'), (34, 'fload_0'), (35, 'fload_1'),
    (36, 'fload_2'), (37, 'fload_3'), (38, 'dload_0'), (39, 'dload_1'),
    (40, 'dload_2'), (41, 'dload_3'), (42, 'aload_0'), (43, 'aload_1'),
    (44, 'aload_2'), (45, 'aload_3'), (46, 'iaload'), (47, 'laload'),
    (48, 'faload'), (49, 'daload'), (50, 'aaload'), (51, 'baload'),
    (52, 'caload'), (53, 'saload'), (54, 'istore'), (55, 'lstore'),
    (56, 'fstore'), (57, 'dstore'), (58, 'astore'), (59, 'istore_0'),
    (60, 'istore_1'), (61, 'istore_2'), (62, 'istore_3'), (63, 'lstore_0'),
    (64, 'lstore_1'), (65, 'lstore_2'), (66, 'lstore_3'), (67, 'fstore_0'),
    (68, 'fstore_1'), (69, 'fstore_2'), (70, 'fstore_3'), (71, 'dstore_0'),
    (72, 'dstore_1'), (73, 'dstore_2'), (74, 'dstore_3'), (75, 'astore_0'),
    (76, 'astore_1'), (77, 'astore_2'), (78, 'astore_3'), (79, 'iastore'),
    (80, 'lastore'), (81, 'fastore'), (82, 'dastore'), (83, 'aastore'),
    (84, 'bastore'), (85, 'castore'), (86, 'sastore'), (87, 'pop'),
    (88, 'pop2'), (89, 'dup'), (90, 'dup_x1'), (91, 'dup_x2'),
    (92, 'dup2'), (93, 'dup2_x1'), (94, 'dup2_x2'), (95, 'swap'),
    (96, 'iadd'), (97, 'ladd'), (98, 'fadd'), (99, 'dadd'), (100, 'isub'),
    (101, 'lsub'), (102, 'fsub'), (103, 'dsub'), (104, 'imul'),
    (105, 'lmul'), (106, 'fmul'), (107, 'dmul'), (108, 'idiv'),
    (109, 'ldiv'), (110, 'fdiv'), (111, 'ddiv'), (112, 'irem'),
    (113, 'lrem'), (114, 'frem'), (115, 'drem'), (116, 'ineg'),
    (117, 'lneg'), (118, 'fneg'), (119, 'dneg'), (120, 'ishl'),
    (121, 'lshl'), (122, 'ishr'), (123, 'lshr'), (124, 'iushr'),
    (125, 'lushr'), (126, 'iand'), (127, 'land'), (128, 'ior'),
    (129, 'lor'), (130, 'ixor'), (131, 'lxor'), (132, 'iinc'),
    (133, 'i2l'), (134, 'i2f'), (135, 'i2d'), (136, 'l2i'), (137, 'l2f'),
    (138, 'l2d'), (139, 'f2i'), (140, 'f2l'), (141, 'f2d'), (142, 'd2i'),
    (143, 'd2l'), (144, 'd2f'), (145, 'i2b'), (146, 'i2c'), (147, 'i2s'),
    (148, 'lcmp'), (149, 'fcmpl'), (150, 'fcmpg'), (151, 'dcmpl'),
    (152, 'dcmpg'), (153, 'ifeq'), (154, 'ifne'), (155, 'iflt'),
    (156, 'ifge'), (157, 'ifgt'), (158, 'ifle'), (159, 'if_icmpeq'),
    (160, 'if_icmpne'), (161, 'if_icmplt'), (162, 'if_icmpge'),
    (163, 'if_icmpgt'), (164, 'if_icmple'), (165, 'if_acmpeq'),
    (166, 'if_acmpne'), (167, 'goto'), (168, 'jsr'), (169, 'ret'),
    (170, 'tableswitch'), (171, 'lookupswitch'), (172, 'ireturn'),
    (173, 'lreturn'), (174, 'freturn'), (175, 'dreturn'), (176, 'areturn'),
    (177, 'return'), (178, 'getstatic'), (179, 'putstatic'), (180, 'getfield'),
    (181, 'putfield'), (182, 'invokevirtual'), (183, 'invokespecial'),
    (184, 'invokestatic'), (185, 'invokeinterface'), (186, 'xxxunused'),
    (187, 'new'), (188, 'newarray'), (189, 'anewarray'), (190, 'arraylength'),
    (191, 'athrow'), (192, 'checkcast'), (193, 'instanceof'),
    (194, 'monitorenter'), (195, 'monitorexit'), (196, 'wide'),
    (197, 'multianewarray'), (198, 'ifnull'), (199, 'ifnonnull'),
    (200, 'goto_w'), (201, 'jsr_w')]:
    OPS[_op] = _nm


def disasm(code, cp_str):
    out = []
    p = 0
    n = len(code)
    while p < n:
        off = p
        op = code[p]
        p += 1
        name = OPS.get(op, f'op{op}')
        arg = ''
        try:
            if name in ('bipush',):
                arg = str(struct.unpack('b', code[p:p + 1])[0])
                p += 1
            elif name in ('sipush',):
                arg = str(struct.unpack('>h', code[p:p + 2])[0])
                p += 2
            elif name in ('ldc', 'iload', 'lload', 'fload', 'dload', 'aload',
                          'istore', 'lstore', 'fstore', 'dstore', 'astore', 'ret'):
                arg = f'#{code[p]} {cp_str(code[p])}' if name == 'ldc' else str(code[p])
                p += 1
            elif name in ('ldc_w', 'ldc2_w', 'getstatic', 'putstatic', 'getfield',
                          'putfield', 'invokevirtual', 'invokespecial', 'invokestatic',
                          'new', 'anewarray', 'checkcast', 'instanceof'):
                idx = struct.unpack('>H', code[p:p + 2])[0]
                arg = f'#{idx} {cp_str(idx)}'
                p += 2
            elif name == 'invokeinterface':
                idx = struct.unpack('>H', code[p:p + 2])[0]
                arg = f'#{idx} {cp_str(idx)} nargs={code[p + 2]}'
                p += 4
            elif name == 'iinc':
                arg = '%d %d' % (code[p], struct.unpack('b', code[p + 1:p + 2])[0])
                p += 2
            elif name == 'newarray':
                arg = {4: 'bool', 5: 'char', 6: 'float', 7: 'double', 8: 'byte',
                       9: 'short', 10: 'int', 11: 'long'}[code[p]]
                p += 1
            elif name == 'multianewarray':
                idx = struct.unpack('>H', code[p:p + 2])[0]
                arg = f'#{idx} {cp_str(idx)} dims={code[p + 2]}'
                p += 3
            elif name in ('ifeq', 'ifne', 'iflt', 'ifge', 'ifgt', 'ifle',
                          'if_icmpeq', 'if_icmpne', 'if_icmplt', 'if_icmpge',
                          'if_icmpgt', 'if_icmple', 'if_acmpeq', 'if_acmpne',
                          'goto', 'jsr', 'ifnull', 'ifnonnull'):
                arg = '->%d' % (off + struct.unpack('>h', code[p:p + 2])[0])
                p += 2
            elif name in ('goto_w', 'jsr_w'):
                arg = '->%d' % (off + struct.unpack('>i', code[p:p + 4])[0])
                p += 4
            elif name in ('tableswitch', 'lookupswitch'):
                start = p
                while (off + 1 + (p - off - 1)) % 4:
                    p += 1
                pad = p - start
                default = struct.unpack('>i', code[p:p + 4])[0]
                p += 4
                if name == 'tableswitch':
                    lo = struct.unpack('>i', code[p:p + 4])[0]
                    hi = struct.unpack('>i', code[p + 4:p + 8])[0]
                    p += 8
                    tg = [struct.unpack('>i', code[p + 4 * k:p + 4 * k + 4])[0] for k in range(hi - lo + 1)]
                    p += 4 * len(tg)
                    arg = f'def->{off + default} ' + ' '.join(f'{lo + k}->{off + t}' for k, t in enumerate(tg))
                else:
                    nn = struct.unpack('>i', code[p:p + 4])[0]
                    p += 4
                    pairs = [(struct.unpack('>i', code[p + 8 * k:p + 8 * k + 4])[0],
                              struct.unpack('>i', code[p + 8 * k + 4:p + 8 * k + 8])[0]) for k in range(nn)]
                    p += 8 * nn
                    arg = f'def->{off + default} ' + ' '.join(f'{k}->{off + t}' for k, t in pairs)
            elif name == 'wide':
                op2 = code[p]
                p += 1
                name2 = OPS.get(op2, f'op{op2}')
                idx = struct.unpack('>H', code[p:p + 2])[0]
                p += 2
                if name2 == 'iinc':
                    arg = '%s %d %d' % (name2, idx, struct.unpack('>h', code[p:p + 2])[0])
                    p += 2
                else:
                    arg = '%s %d' % (name2, idx)
                name = 'wide ' + name2
        except Exception as e:
            arg = f'<decode-error {e}>'
            p = n
        out.append(f'{off:5d}  {name:16s} {arg}')
    return out


def load_class(path):
    if '.jar!' in path or (path.endswith('.jar') is False and '!' in path):
        jar, inner = path.split('!', 1)
        z = zipfile.ZipFile(jar)
        return z.read(inner.lstrip('!/'))
    if path.endswith('.jar'):
        raise SystemExit('give jar!inner/path or a .class file')
    with open(path, 'rb') as f:
        return f.read()


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    only = None
    if '--method' in args:
        i = args.index('--method')
        only = args[i + 1]
        del args[i:i + 2]
    data = load_class(args[0])
    cname, cp, cp_str, fields, methods = parse_class(data)
    print(f'class {cname}')
    for fn, fd, fa in fields:
        print(f'  field {fn}:{fd} {fa}')
    for mn, md, code in methods:
        if only and mn != only:
            continue
        print(f'  method {mn}{md}')
        if code:
            for line in disasm(code, cp_str):
                print('   ', line)


if __name__ == '__main__':
    main()
