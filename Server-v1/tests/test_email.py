"""Email claims: 63003 grants one indexed item, 63006/63007 move the mail
JB/YB purse on-role, 63008 sweeps one mail's items plus both purses.

Evidence: EmailAction.attachment/jb/yb/onekey input shapes
([emailId, index] / [emailId]) and RoleEmailServiceImpl.lingquAttachment /
lingquJb / lingquYb / onekey reply shapes ([1, emailId, index] /
[1, amount] / [1, jb, yb, itemVos]) with EmailErrorCode gates 60001
missing mail, 60002 no attachment, 60005/60006 empty JB/YB purse, 60007
bag full. The item-VO tail is a [goodsId, count] simplification of
StoreGoodsOutput.formart2.
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
from game.config import GameConfig  # noqa: E402
from game.protocol import Session  # noqa: E402

REAL_CONFIG = os.path.join(os.path.dirname(__file__), '..', '..',
                           'reference', 'TonNgoKhong', 'server', 'config',
                           'game')
HAVE_REAL = os.path.isdir(REAL_CONFIG)


@unittest.skipUnless(HAVE_REAL, 'legacy config tree not present')
class EmailClaimTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(os.path.join(self.tmp.name, 'm.db'))
        self.addCleanup(self.store.close)
        self.store.create_account('hero', hash_password('pw'))
        self.role_id = self.store.create_character(
            'hero', 'fu1304', 'Wukong', job='C', level=56,
            tongqian=1000, lingshi=50)
        self.store.save_role_bag_state(self.role_id, bag_capacity=144,
                                       storage_capacity=31)
        self.cfg = GameConfig(str(REAL_CONFIG))
        self.sess = Session(
            conn_id=1, check_sign=lambda *a: False,
            get_roles=lambda u, s: [dict(r) for r in
                                    self.store.list_roles(u, s)],
            server_start_ms=0,
            save_role_state=self.store.update_character_state,
            get_role_email=self.store.get_role_email,
            update_role_email=self.store.update_role_email,
            get_role_bag_slots=self.store.get_role_bag_slots,
            get_role_bag_state=self.store.get_role_bag_state,
            update_role_bag_slot=self.store.update_role_bag_slot,
            insert_role_bag_slot=self.store.insert_role_bag_slot,
            save_role_bag_state=self.store.save_role_bag_state,
            config=self.cfg)
        self.sess.authed_user, self.sess.server_id = 'hero', 'fu1304'

    @staticmethod
    def frames(out):
        if isinstance(out, (bytes, bytearray)):
            return [decode(bytes(out)[4:])]
        return [decode(bytes(f)[4:]) for f in out]

    def seed(self, attachment='[]', jb=0, yb=0):
        return self.store.save_role_email(
            str(self.role_id), title='sys', content='gift',
            attachment=attachment, jb=jb, yb=yb)

    def money(self):
        (role,) = [r for r in self.store.list_roles('hero', 'fu1304')
                    if str(r['id']) == str(self.role_id)]
        return int(role['tongqian'] or 0), int(role['lingshi'] or 0)

    def bag(self):
        return {s['goods_id']: s['count'] for s in
                self.store.get_role_bag_slots(self.role_id, 1, 150)}

    def test_missing_mail_is_60001(self):
        (frame,) = self.frames(
            self.sess.email_attachment([63003, ['999', '0']]))
        self.assertEqual(frame, ['63003', [0, 60001]])
        (frame,) = self.frames(self.sess.email_jb([63006, ['999']]))
        self.assertEqual(frame, ['63006', [0, 60001]])
        (frame,) = self.frames(self.sess.email_yb([63007, ['999']]))
        self.assertEqual(frame, ['63007', [0, 60001]])
        (frame,) = self.frames(self.sess.email_onekey([63008, ['999']]))
        self.assertEqual(frame, ['63008', [0, 60001]])

    def test_empty_attachments_is_60002(self):
        mid = self.seed(attachment='[]')
        (frame,) = self.frames(
            self.sess.email_attachment([63003, [str(mid), '0']]))
        self.assertEqual(frame, ['63003', [0, 60002]])
        (frame,) = self.frames(
            self.sess.email_attachment([63003, [str(mid), '7']]))
        self.assertEqual(frame, ['63003', [0, 60002]])

    def test_attachment_claim_grants_item(self):
        mid = self.seed(attachment=json.dumps(
            [{'goodsId': 'silver50', 'goodsCount': 2}]))
        (frame,) = self.frames(
            self.sess.email_attachment([63003, [str(mid), '0']]))
        self.assertEqual(frame, ['63003', [1, str(mid), '0']])
        self.assertEqual(self.bag().get('silver50'), 2)
        row = self.store.get_role_email(str(self.role_id), str(mid))
        self.assertEqual(json.loads(row['attachment'] or '[]'), [])

    def test_attachment_bag_full_is_60007(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=0,
                                       storage_capacity=0)
        mid = self.seed(attachment=json.dumps(
            [{'goodsId': 'silver50', 'goodsCount': 1}]))
        (frame,) = self.frames(
            self.sess.email_attachment([63003, [str(mid), '0']]))
        self.assertEqual(frame, ['63003', [0, 60007]])
        row = self.store.get_role_email(str(self.role_id), str(mid))
        self.assertEqual(len(json.loads(row['attachment'])), 1)

    def test_jb_claim_moves_tongqian(self):
        mid = self.seed(jb=500)
        (frame,) = self.frames(self.sess.email_jb([63006, [str(mid)]]))
        self.assertEqual(frame, ['63006', [1, 500]])
        self.assertEqual(self.money(), (1500, 50))
        row = self.store.get_role_email(str(self.role_id), str(mid))
        self.assertEqual(int(row['jb']), 0)
        (frame,) = self.frames(self.sess.email_jb([63006, [str(mid)]]))
        self.assertEqual(frame, ['63006', [0, 60005]])

    def test_yb_claim_moves_lingshi(self):
        mid = self.seed(yb=30)
        (frame,) = self.frames(self.sess.email_yb([63007, [str(mid)]]))
        self.assertEqual(frame, ['63007', [1, 30]])
        self.assertEqual(self.money(), (1000, 80))
        (frame,) = self.frames(self.sess.email_yb([63007, [str(mid)]]))
        self.assertEqual(frame, ['63007', [0, 60006]])

    def test_onekey_sweeps_all(self):
        mid = self.seed(
            attachment=json.dumps([{'goodsId': 'silver50',
                                    'goodsCount': 3}]),
            jb=200, yb=10)
        (frame,) = self.frames(
            self.sess.email_onekey([63008, [str(mid)]]))
        self.assertEqual(
            frame, ['63008', [1, 200, 10, [['silver50', 3]]]])
        self.assertEqual(self.bag().get('silver50'), 3)
        self.assertEqual(self.money(), (1200, 60))
        row = self.store.get_role_email(str(self.role_id), str(mid))
        self.assertEqual(json.loads(row['attachment'] or '[]'), [])
        self.assertEqual(int(row['jb']), 0)
        self.assertEqual(int(row['yb']), 0)

    def test_onekey_bag_full_keeps_purses(self):
        self.store.save_role_bag_state(self.role_id, bag_capacity=0,
                                       storage_capacity=0)
        mid = self.seed(
            attachment=json.dumps([{'goodsId': 'silver50',
                                    'goodsCount': 1}]),
            jb=200, yb=10)
        (frame,) = self.frames(
            self.sess.email_onekey([63008, [str(mid)]]))
        self.assertEqual(frame, ['63008', [0, 60007]])
        row = self.store.get_role_email(str(self.role_id), str(mid))
        self.assertEqual(int(row['jb']), 200)
        self.assertEqual(int(row['yb']), 10)


if __name__ == '__main__':
    unittest.main()
