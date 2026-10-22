"""Command 136000: PetServiceImpl.getPetInfo -> Object[4].

Evidence: PetAction.getPetInfo (roleId only, send2One '136000') and
PetServiceImpl.getPetInfo bytecode: [0] is one [petId, lv, rank, lvExp,
rankExp] per RolePet (null when the role owns none); [1] is [zhenfaId,
upgradeExp, [[pos, petId]...]] over the zhenfa_pet fastjson map (null
entries when the map is missing/empty); [2] petChuzhanId, [3]
petUpgradeCount. No formation row is silent (Java's cacheLoad miss;
live rows always exist). Entry order follows the JSON document; Java
iterates a HashMap keySet, so multi-entry order is not guaranteed.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from auth import hash_password  # noqa: E402
from db import Store  # noqa: E402
from game.amf3 import decode  # noqa: E402
from game.protocol import Session  # noqa: E402


class PetInfoTest(unittest.TestCase):
    """136000 over seeded role_pet / role_pet_zhenfa rows."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 't.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56)
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            get_role_pets=self.store.get_role_pets,
            save_role_pet=self.store.save_role_pet,
            get_role_pet_zhenfa=self.store.get_role_pet_zhenfa,
            save_role_pet_zhenfa=self.store.save_role_pet_zhenfa)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    def info(self):
        out = self.sess.pet_info()
        return decode(out[4:]) if out is not None else None

    def test_missing_formation_is_silent(self):
        self.assertIsNone(self.info())

    def test_live_shape_zhenfa_only(self):
        # Live role_pet_zhenfa rows: zhenfa '1', no chuzhan, '{}' map.
        self.store.save_role_pet_zhenfa(
            self.role_id, zhenfa_id='1', upgrade_exp=0, zhenfa_pet='{}',
            pet_upgrade_count=0)
        self.assertEqual(
            self.info(), ['136000', [None, ['1', 0, None], None, 0]])

    def test_pets_and_formation_entries(self):
        self.store.save_role_pet(self.role_id, 'petA', pet_lv=12,
                                 pet_lv_exp=300, pet_rank=2,
                                 pet_rank_exp=40)
        self.store.save_role_pet(self.role_id, 'petB', pet_lv=1,
                                 pet_lv_exp=0, pet_rank=0,
                                 pet_rank_exp=0)
        self.store.save_role_pet_zhenfa(
            self.role_id, zhenfa_id='1', pet_chuzhan_id='petA',
            upgrade_exp=7,
            zhenfa_pet=json.dumps({'1': 'petA', '3': 'petB'}),
            pet_upgrade_count=2)
        self.assertEqual(
            self.info(),
            ['136000', [[['petA', 12, 2, 300, 40], ['petB', 1, 0, 0, 0]],
                        ['1', 7, [['1', 'petA'], ['3', 'petB']]],
                        'petA', 2]])

    def test_bad_formation_blob_yields_null_entries(self):
        self.store.save_role_pet_zhenfa(
            self.role_id, zhenfa_id='1', upgrade_exp=0,
            zhenfa_pet='not json', pet_upgrade_count=0)
        self.assertEqual(
            self.info(), ['136000', [None, ['1', 0, None], None, 0]])

    def test_pet_upsert_updates_levels(self):
        self.store.save_role_pet(self.role_id, 'petA', pet_lv=1)
        self.store.save_role_pet(self.role_id, 'petA', pet_lv=5,
                                 pet_lv_exp=90)
        rows = self.store.get_role_pets(self.role_id)
        self.assertEqual(
            rows, [{'pet_id': 'petA', 'pet_lv': 5, 'pet_rank': None,
                    'pet_lv_exp': 90, 'pet_rank_exp': None}])


if __name__ == '__main__':
    unittest.main()
