const SCRIPT = 'sh /data/adb/modules/MFGA/action.sh';
export const COMMANDS = Object.freeze({
    diagnose: `${SCRIPT} diagnose`,
    gms: `${SCRIPT} gms --confirm`,
    blockApps: `${SCRIPT} app-fonts block --confirm`,
    restoreApps: `${SCRIPT} app-fonts restore --confirm`,
});

// The bundled KernelSU bridge has one contract: { errno, stdout, stderr }.
// Never infer success from translated output, an empty stderr or a guessed field.
export function commandResult(result) {
    if (!result || !Number.isInteger(result.errno)) {
        throw new TypeError('Invalid KernelSU result: missing integer errno');
    }
    return { code: result.errno, stdout: String(result.stdout ?? ''), stderr: String(result.stderr ?? '') };
}

export function localeKey(raw) {
    const language = String(raw).trim().split(/[-_,]/)[0].toLowerCase();
    return ({ en: 'en_US', ja: 'ja_JP', ru: 'ru_RU', zh: 'zh_CN' })[language] ?? 'zh_CN';
}
