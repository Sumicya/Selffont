"""主人 2026-10-26 贴出的码位表（按端点展开）。

主人原话只有端点，`…` 是省略写法。这里按「两端之间整段」展开成闭区间，取并集：
宁可比主人要的多，不可少——少了就是又一次「覆盖不到」。
其中 20 个码位到 Unicode 18.0 仍未分配（见 UNASSIGNED），它们没有标准字形，
仍按同一设计规则给出占位字形，不做豆腐块。
"""

RANGES = (
    (0x1F7F1, 0x1F7FF),   # 🟱…🟿  符号（遗产计算补充一带）
    (0x1CED2, 0x1CEFD),   # 𜻒…𜻽
    (0x1246F, 0x1247F),   # 𒑯…𒑿  楔形数字与标点
    (0x1DF4D, 0x1DF54),   # 𝽔…𝽍  拉丁扩展 G
    (0x18E00, 0x18E3B),   # 𘸻…𘸀  女真文
    (0x10EC9, 0x10EF9),   # 𐻉…𐻹  阿拉伯扩展 C
    (0x1FA8B, 0x1FAFA),   # 🪋…🫺  符号与象形
    (0x2E60, 0x2E63),     # ⹠…
    (0xA7DD, 0xA7DD),     # ꟝
    (0xA7E2, 0xA7E2),
    (0x208F, 0x208F),     # ₏
    (0x1095A, 0x1095C),   # 𐥚𐥛𐥜
)

UNASSIGNED = (
    0x1CED5, 0x1CED6, 0x1CED7, 0x1CED8, 0x1CED9, 0x1CEDA, 0x1CEDB, 0x1CEDC,
    0x10EEF, 0x1FAC7, 0x1FAC9, 0x1FACA, 0x1FACB, 0x1FADE,
    0x1FAEC, 0x1FAED, 0x1FAEE, 0x1095A, 0x1095B, 0x1095C,
)

TARGETS = tuple(sorted({cp for lo, hi in RANGES for cp in range(lo, hi + 1)}))
