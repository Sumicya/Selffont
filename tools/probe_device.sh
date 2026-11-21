#!/system/bin/sh
# Selffont 真机探针：一条命令看全（只读，不改任何文件）。
# 跑：su -c 'sh /data/local/tmp/probe.sh'
# 输出直接整段贴回来。

uid=$(id -u)
echo "########## Selffont 真机探针  $(date '+%Y-%m-%d %H:%M:%S %z')  uid=$uid"
[ "$uid" = 0 ] || echo "!! 不是 root：/data/adb 读不到，下面凡是「（无）」都不算数"

echo
echo "===== 1 设备与 Root"
echo "机型 : $(getprop ro.product.brand) $(getprop ro.product.model) / Android $(getprop ro.build.version.release) SDK $(getprop ro.build.version.sdk)"
echo "ROM  : $(getprop ro.build.display.id)"
echo "Root : ksu=$(command -v ksud) apd=$(command -v apd)"
echo "内核 : $(uname -r)"

echo
echo "===== 2 已装模块（id / 目录 / 状态标记）"
for d in /data/adb/modules/*/; do
    [ -f "$d/module.prop" ] || continue
    id=$(sed -n 's/^id=//p' "$d/module.prop")
    ver=$(sed -n 's/^version=//p' "$d/module.prop")
    flag=""
    [ -f "$d/disable" ] && flag="$flag disable(已停用)"
    [ -f "$d/remove" ] && flag="$flag remove(待删)"
    [ -f "$d/update" ] && flag="$flag update(待更新)"
    printf '  %-10s %-22s %s%s\n' "$id" "$ver" "$d" "$flag"
done
[ -d /data/adb/modules/MFGA ] || echo "  → 结论：MFGA 没装（或叫别的 id）"

echo
echo "===== 3 模块内容（Selffont 自己的文件）"
ls -l /data/adb/modules/MFGA/ 2>/dev/null | sed 's/^/  /'
echo "  -- system/ 下有没有带字体或 fonts.xml --"
find /data/adb/modules/MFGA/system -type f 2>/dev/null | sed 's/^/  /'
n_xml=$(find /data/adb/modules/MFGA -name fonts.xml 2>/dev/null | wc -l | tr -d ' ')
echo "  模块内 fonts.xml 份数：$n_xml"
[ "$n_xml" = 0 ] && echo "  → 结论：Skia 那条路是关的（默认，正确）" || echo "  → 结论：模块里带了 fonts.xml，Flutter 会读它"

echo
echo "===== 4 开关状态"
cat /data/adb/selffont-skia.state 2>/dev/null | sed 's/^/  skia.state: /' || echo "  skia.state: （无 → 默认 off）"
ls -l /data/adb/selffont* 2>/dev/null | sed 's/^/  /'

echo
echo "===== 5 真正生效的字（挂载层与 /system/fonts）"
m=/proc/1/mounts; [ -r "$m" ] || m=/proc/mounts
echo "  字体相关挂载：$(grep -ci 'MFGA\|selffont' "$m") 条"
grep -i 'MFGA\|selffont' "$m" 2>/dev/null | sed 's/^/    /'
echo "  /system/fonts 里的 Self 系文件："
n_font=$(ls -l /system/fonts/ 2>/dev/null | grep -ci 'self\|MFGA')
if [ "${n_font:-0}" = 0 ]; then echo "    （无 → 模块没接管字体）"
else ls -l /system/fonts/ | grep -i 'self\|MFGA' | sed 's/^/    /'; fi
n_self=$(grep -c 'Selfrounds' /system/etc/fonts.xml 2>/dev/null)
echo "  /system/etc/fonts.xml 里 Selfrounds 出现次数：${n_self:-0}"

echo
echo "===== 6 安装期自检日志（末尾 40 行）"
if [ -f /data/adb/selffont-selftest.log ]; then
    tail -40 /data/adb/selffont-selftest.log | sed 's/^/  /'
    echo "  -- 关键行 --"
    grep -n 'Skia\|skia\|字体\|fonts.xml\|失败\|错误\|error' /data/adb/selffont-selftest.log 2>/dev/null | tail -12 | sed 's/^/  /'
else
    echo "  （无 /data/adb/selffont-selftest.log → 装的时候没写日志，或不是本模块）"
fi

echo
echo "===== 7 备份 / 垃圾（只列不删）"
echo "  -- *.bak / *.orig / *~ --"
find /storage/emulated/0/Download /data/adb/modules /data/local/tmp -maxdepth 3 \
     \( -name '*.bak' -o -name '*.orig' -o -name '*~' \) 2>/dev/null | sed 's/^/    /'
echo "  -- ksubak / disablebak --"
find /storage/emulated/0/Download /data/adb /data/local/tmp -maxdepth 5 \
     \( -iname 'ksubak*' -o -iname '*disablebak*' \) 2>/dev/null | sed 's/^/    /'
echo "  -- selffont 临时件 --"
find /data/local/tmp /data/adb -maxdepth 2 -name 'selffont*' 2>/dev/null | sed 's/^/    /'

echo
echo "===== 8 开机脚本里碰字体的（只读）"
found=0
for dir in /data/adb/service.d /data/adb/post-fs-data.d; do
    for f in "$dir"/*; do
        [ -f "$f" ] || continue
        if grep -qsi 'font\|selffont\|MFGA' "$f"; then
            found=1; echo "  $f"; grep -nsi 'font\|selffont\|MFGA' "$f" | head -3 | sed 's/^/    /'
        fi
    done
done
[ "$found" = 1 ] || echo "  （无）"

echo
echo "########## 完。把上面整段贴回来。"
