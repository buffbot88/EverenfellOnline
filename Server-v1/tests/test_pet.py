"""Commands 136000/136005/136006: pet info, formation deploy, expedition.

Evidence: @EasyMapping on PetAction (136000 getPetInfo, 136005
upDownZhen, 136006 chuZhan, 136008 chuanChen, 136009 jinJieZhenFa;
136007 has no handler jar-wide) and PetServiceImpl._downZhen/upZhen/
chuZhan bytecode. 136000 answers [pets, [zhenfaId, upgradeExp, entries],
chuzhanId, upgradeCount]; 136005 [petId, slot, 1] deploys ([0, 136005]
unknown pet, [0, 136006] already deployed) while other flags remove
the slot, both emitting the 136010 [[pos, petId]] push and answering
[1, ...]; 136006 [deploys/recalls the expedition pet ([0, 136005]
unknown, [0, 136010] already deployed), strips it from formation
first, pushes 136011 [[old, 2]] / [[new, 1]] / [[old, 2], [new, 1]]
and answers [1]. 136001/136002/136003/136004/136008/136009 need
the ChongWu config tables, which do not ship, so they stay unported.

136000 detail: [0] is one [petId, lv, rank, lvExp, rankExp] per RolePet
(null when the role owns none); [1] is [zhenfaId, upgradeExp,
[[pos, petId]...]] over the zhenfa_pet fastjson map (null entries when
the map is missing/empty); [2] petChuzhanId, [3] petUpgradeCount. No
formation row is silent (Java's cacheLoad miss; live rows always
exist). Entry order follows the JSON document; Java iterates a HashMap
keySet, so multi-entry order is not guaranteed.
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


class PetFormationTest(unittest.TestCase):
    """136005/136006 over seeded role_pet / role_pet_zhenfa rows."""

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

    def seed(self, pets=('petA',), zhenfa_pet=None, chuzhan=None):
        for pet in pets:
            self.store.save_role_pet(self.role_id, pet, pet_lv=1)
        self.store.save_role_pet_zhenfa(
            self.role_id, zhenfa_id='1', pet_chuzhan_id=chuzhan,
            upgrade_exp=0,
            zhenfa_pet=(json.dumps(zhenfa_pet) if zhenfa_pet is not None
                        else '{}'),
            pet_upgrade_count=0)

    def call(self, fn, *args):
        out = fn(*args)
        if out is None:
            return None
        if isinstance(out, (bytes, bytearray)):
            return [decode(bytes(out)[4:])]
        return [decode(bytes(f)[4:]) for f in out]

    def zhenfa(self):
        return self.store.get_role_pet_zhenfa(str(self.role_id))

    def test_missing_formation_is_silent(self):
        self.store.save_role_pet(self.role_id, 'petA', pet_lv=1)
        self.assertIsNone(
            self.call(self.sess.pet_updown, [136005, ['petA', 1, 1]]))
        self.assertIsNone(
            self.call(self.sess.pet_chuzhan, [136006, 'petA']))

    def test_updown_unknown_pet_is_136005(self):
        self.seed(pets=())
        self.assertEqual(
            self.call(self.sess.pet_updown, [136005, ['ghost', 1, 1]]),
            [['136005', [0, 136005]]])

    def test_updown_deploy_pushes_and_replies(self):
        self.seed()
        self.assertEqual(
            self.call(self.sess.pet_updown, [136005, ['petA', 2, 1]]),
            [['136010', [['2', 'petA']]],
             ['136005', [1, 'petA', 2, 1]]])
        self.assertEqual(json.loads(self.zhenfa()['zhenfa_pet']),
                         {'2': 'petA'})

    def test_updown_duplicate_is_136006(self):
        self.seed(zhenfa_pet={'1': 'petA'})
        self.assertEqual(
            self.call(self.sess.pet_updown, [136005, ['petA', 3, 1]]),
            [['136005', [0, 136006]]])
        self.assertEqual(json.loads(self.zhenfa()['zhenfa_pet']),
                         {'1': 'petA'})

    def test_updown_remove_clears_slot(self):
        self.seed(zhenfa_pet={'1': 'petA', '2': 'petA'})
        out = self.call(self.sess.pet_updown, [136005, ['petA', 1, 0]])
        # AMF3 dynamic-object envelope around the remaining map.
        out[1][1][1] = out[1][1][1].get('__assoc__', out[1][1][1])
        self.assertEqual(
            out,
            [['136010', [['2', 'petA']]],
             ['136005', [1, {'2': 'petA'}, 1, 0]]])
        self.assertEqual(json.loads(self.zhenfa()['zhenfa_pet']),
                         {'2': 'petA'})

    def test_chuzhan_unknown_pet_is_136005(self):
        self.seed(pets=())
        self.assertEqual(
            self.call(self.sess.pet_chuzhan, [136006, 'ghost']),
            [['136006', [0, 136005]]])

    def test_chuzhan_deploy_strips_pushes_replies(self):
        self.seed(pets=('petA', 'petB'),
                  zhenfa_pet={'1': 'petA', '3': 'petB'})
        self.assertEqual(
            self.call(self.sess.pet_chuzhan, [136006, 'petA']),
            [['136010', [['3', 'petB']]],
             ['136011', [['petA', 1]]],
             ['136006', [1]]])
        row = self.zhenfa()
        self.assertEqual(row['pet_chuzhan_id'], 'petA')
        self.assertEqual(json.loads(row['zhenfa_pet']), {'3': 'petB'})

    def test_chuzhan_duplicate_is_136010(self):
        self.seed(chuzhan='petA')
        self.assertEqual(
            self.call(self.sess.pet_chuzhan, [136006, 'petA']),
            [['136006', [0, 136010]]])

    def test_chuzhan_recall_pushes_old(self):
        self.seed(chuzhan='petA')
        self.assertEqual(
            self.call(self.sess.pet_chuzhan, [136006, None]),
            [['136011', [['petA', 2]]],
             ['136006', [1]]])
        self.assertIsNone(self.zhenfa()['pet_chuzhan_id'])

    def test_chuzhan_switch_pushes_both(self):
        self.seed(pets=('petA', 'petB'), chuzhan='petA')
        self.assertEqual(
            self.call(self.sess.pet_chuzhan, [136006, 'petB']),
            [['136011', [['petA', 2], ['petB', 1]]],
             ['136006', [1]]])
        self.assertEqual(self.zhenfa()['pet_chuzhan_id'], 'petB')


if __name__ == '__main__':
    unittest.main()
