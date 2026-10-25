import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const window = {};
const source = await readFile(new URL('./public/access.js', import.meta.url), 'utf8');
vm.runInNewContext(source, { window, fetch() {} });
const access = window.EverenfellAccess;

test('play UI requires the server-confirmed S1 entitlement', () => {
  assert.equal(access.canPlay(null), false);
  assert.equal(access.canPlay({ role: 'Admin', everenfell_s1: false, can_play: false }), false);
  assert.equal(access.canPlay({ role: 'Admin', everenfell_s1: true, can_play: false }), false);
  assert.equal(access.canPlay({ role: 'Admin', everenfell_s1: true, can_play: true }), true);
  assert.equal(access.canPlay({ role: 'Member', everenfell_s1: true, can_play: false }), false);
});
