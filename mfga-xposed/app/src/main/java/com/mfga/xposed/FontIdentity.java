package com.mfga.xposed;

/**
 * Single source of truth for the installed primary font's family name and path.
 *
 * <p>De-hardcoding: the family/path used to be repeated in every class that needed
 * them. Centralising here means swapping the installed font (e.g. a different
 * variable family) only touches one place. The values still match
 * {@code config/font-source.json} ({@code family} / {@code installedFile}); the
 * font packager remains the authority that verifies the file's hash and axes.
 */
public final class FontIdentity {
    /** Matches {@code family} in config/font-source.json. */
    public static final String FAMILY = "WenYuan Rounded SC VF";
    /** Matches {@code /system/fonts/} + {@code installedFile} in config/font-source.json. */
    public static final String FONT_PATH = "/system/fonts/Selffont-WenYuanRoundedSCVF.ttf";

    private FontIdentity() {}
}
