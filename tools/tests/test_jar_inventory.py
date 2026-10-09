"""Tests for tools/jar_inventory.py against the legacy server jar."""
import importlib.util
import os
import sys
import unittest
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOLS = os.path.join(ROOT, 'tools')
sys.path.insert(0, TOOLS)
_spec = importlib.util.spec_from_file_location(
    'jar_inventory', os.path.join(TOOLS, 'jar_inventory.py'))
inv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inv)

JAR = os.path.join(ROOT, 'reference', 'TonNgoKhong', 'server', 'dntg_start.jar')


@unittest.skipUnless(os.path.exists(JAR), 'legacy server jar not present')
class JarInventoryTest(unittest.TestCase):
    def scan(self, inner):
        with zipfile.ZipFile(JAR) as z:
            return inv.scan_class(z.read(inner))

    def test_action_method_maps_to_its_commands(self):
        # RoleAction sends 12011 (ewaiInfo), 19001 (fangWaiGua), 12200
        # (queryRoleByName); verified by hand against the bytecode.
        name, commands, _refs = self.scan(
            'com/xianling/bus/role/easyaction/RoleAction.class')
        self.assertEqual(name, 'com.xianling.bus.role.easyaction.RoleAction')
        self.assertIn('12011', commands)
        self.assertIn('19001', commands)
        self.assertIn('ewaiInfo', commands['12011'])

    def test_stage_controll_owns_world_entry_commands(self):
        _name, commands, _refs = self.scan(
            'com/xianling/bus/stagecontroll/easyaction/StageControllAction.class')
        self.assertIn('10003', commands)
        self.assertIn('20000', commands)

    def test_module_kind_detection(self):
        self.assertEqual(inv.module_kind('com.x.bus.role.command.RoleCommands'),
                         'Commands')
        self.assertEqual(inv.module_kind('com.x.bus.role.easyaction.RoleAction'),
                         'Action')
        self.assertIsNone(inv.module_kind('com.kernel.pool.executor.Message'))

    def test_limit_bounds_the_scan(self):
        by_cmd, modules, errors = inv.build(JAR, limit=25)
        self.assertEqual(errors, [])
        self.assertLessEqual(len(modules), 25)


if __name__ == '__main__':
    unittest.main()
