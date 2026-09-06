import assert from 'node:assert/strict';
import { test } from 'node:test';
import { COMMANDS, commandResult, localeKey } from '../webroot/commands.mjs';

test('KernelSU errno is the only command success signal', () => {
    assert.equal(commandResult({ errno: 1, stdout: '[success]', stderr: '' }).code, 1);
    assert.equal(commandResult({ errno: 0, stdout: '', stderr: 'warning' }).code, 0);
    for (const invalid of [null, 'success', { exitCode: 0 }, { errno: '0' }, { errno: NaN }]) {
        assert.throws(() => commandResult(invalid), TypeError);
    }
});
test('all modifying operations are fixed and explicitly confirmed', () => {
    assert.equal(Object.keys(COMMANDS).length, 4);
    for (const [name, command] of Object.entries(COMMANDS)) {
        assert.ok(command.startsWith('sh /data/adb/modules/MFGA/action.sh '));
        if (name !== 'diagnose') assert.ok(command.endsWith('--confirm'));
    }
    assert.ok(Object.isFrozen(COMMANDS));
});
test('locale fallback is deterministic', () => {
    for (const [input, result] of [['en-GB','en_US'], ['zh-Hans-CN','zh_CN'], ['ru_RU','ru_RU'], ['ja-JP','ja_JP'], ['xx','zh_CN']]) {
        assert.equal(localeKey(input), result);
    }
});
