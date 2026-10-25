import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const window = {};
const source = await readFile(new URL('./public/access.js', import.meta.url), 'utf8');
vm.runInNewContext(source, { window, fetch() {} });
const access = window.EverenfellAccess;

test('maintenance allows admins only; normal mode allows signed-in members', () => {
  assert.equal(access.canPlay(null), false);
  assert.equal(access.canPlay({ role: 'Member' }), false);
  assert.equal(access.canPlay({ role: 'Admin' }), true);
  assert.equal(access.canPlay({ role: 'admin' }), true);
  access.maintenance = false;
  assert.equal(access.canPlay({ role: 'Member' }), true);
});
