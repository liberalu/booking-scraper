import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('production dashboard has no runtime compiler or development React', async () => {
  const html = await readFile('public/build/hifi/index.html', 'utf8');

  assert.doesNotMatch(html, /text\/babel|babel\.min\.js|react\.development/);
  assert.match(html, /\/build\/hifi\/vendor\/react\.js/);
  assert.match(html, /\/build\/hifi\/hf-runs\.js/);
});
