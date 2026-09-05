# This targets the LSPosedLogDaemon record format observed on the test device.
# Match the origin fields, not a keyword appearing inside another module's message.
/^\[[^]]*\][[:space:]]+\([^)]*\)\[com[.]mfga[.]xposed,Selffont,[^]]*\][[:space:]]/ {
    if (!seen[$0]++) {
        count++
        recent[count % 300] = $0
    }
}
END {
    if (count == 0) {
        print "[logs-no-match] No current Selffont origin records; not an injection verdict."
    } else {
        first = count > 300 ? count - 299 : 1
        for (i = first; i <= count; i++) print recent[i % 300]
    }
}
