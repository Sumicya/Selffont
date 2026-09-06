import { exec } from './assets/kernelsu.js';
import { COMMANDS, commandResult, localeKey } from './commands.mjs';

const output = document.getElementById('output');
const buttons = [...document.querySelectorAll('[data-action]')];
let messages = {};
let busy = false;
const FALLBACK = { CONFIRM: '确定执行此手动操作？', OK: '命令结束', FAILED: '失败', COPY_FAILED: '复制失败' };
const t = key => messages[key] ?? FALLBACK[key] ?? document.querySelector(`[data-i18n="${key}"]`)?.textContent ?? key;
const log = text => { output.textContent += `${text}\n`; output.scrollTop = output.scrollHeight; };

async function translate() {
    let locale = 'zh_CN';
    try {
        const result = commandResult(await exec('getprop persist.sys.locale'));
        if (result.code === 0) locale = localeKey(result.stdout);
    } catch (_) { /* A normal browser has no root bridge. Keep the Chinese document. */ }
    try {
        const response = await fetch(`./strings/locales/${locale}.json`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        messages = await response.json();
        document.documentElement.lang = locale.replace('_', '-');
        document.querySelectorAll('[data-i18n]').forEach(element => {
            const text = messages[element.dataset.i18n];
            if (typeof text === 'string') element.textContent = text;
        });
    } catch (error) { log(String(error)); }
}

async function run(action) {
    if (busy || !Object.hasOwn(COMMANDS, action)) return;
    if (action !== 'diagnose') {
        const explanation = action === 'gms' ? t('GMS_WARNING') : t('APPS_WARNING');
        if (!window.confirm(`${explanation}\n\n${t('CONFIRM')}`)) return;
    }
    busy = true;
    buttons.forEach(button => { button.disabled = true; });
    try {
        log(`> ${action}`);
        const result = commandResult(await exec(COMMANDS[action]));
        if (result.stdout) log(result.stdout.trimEnd());
        if (result.stderr) log(result.stderr.trimEnd());
        log(`[${result.code === 0 ? t('OK') : t('FAILED')}] exit=${result.code}`);
    } catch (error) { log(`[${t('FAILED')}] ${error}`); }
    finally {
        busy = false;
        buttons.forEach(button => { button.disabled = false; });
    }
}

buttons.forEach(button => button.addEventListener('click', () => run(button.dataset.action)));
document.getElementById('clear').addEventListener('click', () => { output.textContent = ''; });
document.getElementById('copy').addEventListener('click', async () => {
    try { await navigator.clipboard.writeText(output.textContent); }
    catch (_) { log(t('COPY_FAILED')); }
});
// Only a read of the locale occurs here. No action is invoked on page load.
await translate();

if (typeof window.ksu === 'undefined') {
    buttons.forEach(button => { button.disabled = true; });
    log('Preview: KernelSU bridge unavailable. Root actions are disabled; the font comparison page is read-only.');
}
