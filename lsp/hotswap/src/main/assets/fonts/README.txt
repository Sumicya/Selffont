把要热切换的字体按「家族名.ttf」放在这个目录，编进 APK。

例：sans-serif.ttf、sans-serif-medium.ttf、serif.ttf、monospace.ttf

家族名就是 Typeface.sSystemFontMap 的 key，与系统 fonts.xml 里写的一致；
本目录为空时模块照常工作，只是不替换任何家族（日志会写一行「没有 assets/fonts/*.ttf」）。

为什么放在 APK 里而不放 /data/adb：/data/adb 是 root 专属，普通应用进程读不到。
装新 APK + 重启目标应用即可换字，不用重启整机。
