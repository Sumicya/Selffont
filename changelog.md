# Selffont 第一阶段（未发布诊断版）

- 文渊圆体固定资源与配置生成、KSU/Oplus/Android 16 支持边界。
- 删除上色及字体屏蔽；额外干预仅手动。
- 现代 API 102 单入口；Gecko 155.0.1 启动字体首选项适配及分层诊断。
- 真机安装、APK 构建与网页覆盖尚待相应验证；参见 README.md。

---

以下是上游历史记录，不是当前功能清单。

CN
 
17.0.1.08-31-alpha2(1717180003)
 - 1.适配HyperOS4
 - 2.同步/新增部分字体，调整部分私用区符号颜色
 - 3*.新增Xposed版本MFGA覆盖一些内置了字体的应用
 - 4.增加了对部分Unicode18彩色Emoji的初步支持(早期预览版)
```
🛙🪋🪌🪍🫌🫝🫫🫹🫺
```
 
17.0.0.06-27-alpha(1717180001)
 - 1.同步Roboto到3.0.16(SU)
 - 2.WebUI新增主字体上色，需支持COLRv0，Android10及以上
 - 3.调整主字体中部分组合类符号，修复缺失、在高安卓版本显示异常的情况
 

-------
EN
 
17.0.1.08-31-alpha2(1717180003)
 - 1.Added support for HyperOS 4
 - 2.Synced/Added some fonts and adjusted the colors of some Private Use Area symbols
 - 3*.Added an Xposed version of MFGA to override fonts in some apps with built-in fonts
 - 4.Added preliminary support for some Unicode 18 colored emoji (early preview)
```
🛙🪋🪌🪍🫌🫝🫫🫹🫺
```
 
17.0.0.06-27-alpha(1717180001)
 - 1.Synchronized Roboto font to version 3.0.16(SU).
 - 2.Added main font colorization in WebUI; requires COLRv0 support, Android 10 and above.
 - 3.Adjusted some composite symbols in the main font, fixing missing glyphs and display issues on higher Android versions.
 

Telegram channel:

https://t.me/AndroidCoreLayer

Power by:

Yiyunlengyu(酷安@Numbersf)