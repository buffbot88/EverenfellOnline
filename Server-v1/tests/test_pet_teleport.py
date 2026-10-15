"""Pet teleport-to-owner goldens (PetFightServiceImpl.defaultHandle / telport).

Oracle, from dntg_start.jar via tools/javap.py: defaultHandle teleports the pet when
inScope(owner, pet, 10, GRID) fails, which is Chebyshev distance > 10. telport finds
the owner's surround valid point, calls teleportTo, then sends 40100 [x, y, 0, petId]
with send2Many to the surround role ids of the pet's new position.
"""
import os
import shutil
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from game import amf3  # noqa: E402
from game.protocol import Session  # noqa: E402
from game.stage_registry import StageRegistry  # noqa: E402
from test_ai import synthetic_config, write_bytes  # noqa: E402


def make_config():
    root = tempfile.mkdtemp()
    cfg = synthetic_config(root)
    # Overwrite the 8x8 grid synthetic_config writes: an open 16x16 grid lets the owner
    # stand more than 10 tiles from the pet.
    write_bytes(root, 'map_config/7/path.mm', struct.pack('>ii', 16, 16) + bytes([0x1F] * 256))
    return cfg, root


def decode(frames):
    return [amf3.decode(f[4:]) for f in frames or []]


class PetTeleportTest(unittest.TestCase):
    def setUp(self):
        self.cfg, root = make_config()
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self.reg = StageRegistry()
        self.owner_role = {'id': 1, 'name': 'Wukong', 'map_id': '7', 'map_x': 12,
                           'map_y': 12, 'level': 1, 'exp': 0, 'zhenqi': 0}

    def session(self, conn_id, role=None):
        roles = [role] if role else []
        sess = Session(conn_id=conn_id, check_sign=lambda *a: False,
                       get_roles=lambda u, s: roles, server_start_ms=0,
                       config=self.cfg, stage_registry=self.reg)
        sess.authed_user, sess.server_id = 'hero', 'fu1304'
        return sess

    def pet_at(self, sess, pos):
        sess._pet_state['zuoqi_7_1'] = {
            'max_hp': 500.0, 'hp': 500.0, 'level': 1, 'owner': '1',
            'owner_name': 'Wukong', 'name': 'mount', 'template_id': 'zuoqi1',
            'pos': list(pos)}
        return sess._pet_state['zuoqi_7_1']

    def test_distant_pet_teleports_beside_owner(self):
        sess = self.session(1, self.owner_role)
        pet = self.pet_at(sess, (1, 1))  # Chebyshev 11 from owner (12, 12)
        out = decode(sess.ai_tick())
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0][0], '40100')
        x, y = pet['pos']
        self.assertEqual(out[0][1], [x, y, 0, 'zuoqi_7_1'])
        self.assertLessEqual(max(abs(x - 12), abs(y - 12)), 1)
        self.assertNotEqual((x, y), (12, 12))

    def test_pet_within_range_steps_instead_of_teleporting(self):
        sess = self.session(1, self.owner_role)
        pet = self.pet_at(sess, (3, 3))  # Chebyshev 9: inside the 10-tile range
        out = decode(sess.ai_tick())
        self.assertEqual([d[0] for d in out], ['40000'])
        self.assertEqual(out[0][1][3:], [2, 'zuoqi_7_1'])
        self.assertEqual(pet['pos'], [4, 4])

    def test_teleport_echo_reaches_surround_peers_only(self):
        owner = self.session(1, self.owner_role)
        peer = self.session(2, {'id': 2, 'name': 'Peer', 'map_id': '7', 'map_x': 13,
                                'map_y': 12, 'level': 1, 'exp': 0, 'zhenqi': 0})
        far = self.session(3, {'id': 3, 'name': 'Far', 'map_id': '7', 'map_x': 60,
                               'map_y': 60, 'level': 1, 'exp': 0, 'zhenqi': 0})
        self.reg.register('1', '7', owner, x=12, y=12)
        self.reg.register('2', '7', peer, x=13, y=12)
        self.reg.register('3', '7', far, x=60, y=60)
        pet = self.pet_at(owner, (1, 1))
        own = decode(owner.ai_tick())
        self.assertEqual([d[0] for d in own], ['40100'])
        echoed = decode(peer.tick(now_ms=0))
        self.assertEqual(echoed, [['40100', [pet['pos'][0], pet['pos'][1], 0, 'zuoqi_7_1']]])
        self.assertIsNone(far.tick(now_ms=0))

    def test_teleport_leaves_monster_hatred_untouched(self):
        # Java's telport path clears the pet's own hatred manager (IPet.getHatredManager),
        # not monsters' hatred toward the pet. The port keeps no pet-side hatred, so the
        # monster keeps its hatred and only the 40100 echo is sent.
        sess = self.session(1, self.owner_role)
        pet = self.pet_at(sess, (1, 1))
        sess._monster_reg['m_7_0'] = {'template': {}, 'map': '7', 'pos': [6, 6],
                                      'born': [4, 4]}
        sess._hatred['m_7_0'] = 'zuoqi_7_1'
        frames = []
        self.assertTrue(sess._pet_teleport('zuoqi_7_1', pet, self.owner_role, frames))
        self.assertEqual(sess._hatred, {'m_7_0': 'zuoqi_7_1'})
        self.assertEqual(sess._monster_reg['m_7_0']['pos'], [6, 6])
        self.assertEqual([d[0] for d in decode(frames)], ['40100'])

    def test_no_valid_cell_falls_back_to_follow_step(self):
        sess = self.session(1, self.owner_role)
        pet = self.pet_at(sess, (1, 1))
        # Owner off the grid: surround_valid_point returns None, so no teleport echo.
        # The pet then falls through to the ordinary follow step, as Java does.
        self.owner_role.update(map_x=40, map_y=40)
        out = decode(sess.ai_tick())
        self.assertEqual([d[0] for d in out], ['40000'])
        self.assertEqual(out[0][1][3:], [2, 'zuoqi_7_1'])
        self.assertEqual(pet['pos'], [2, 2])


if __name__ == '__main__':
    unittest.main()
