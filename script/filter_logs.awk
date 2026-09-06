# Parse the FIRST process/origin boundary, independent of timestamp/logcat prefix.
# Do not search subsequent quoted records in another module's message.
{
    line = $0
    if (!match(line, /\)[[:space:]]*\[/)) next
    origin = substr(line, RSTART + RLENGTH)
    closing = index(origin, "]")
    if (!closing) next
    n = split(substr(origin, 1, closing - 1), fields, ",")
    if (n < 3) next
    for (i = 1; i <= 2; i++) {
        sub(/^[[:space:]]+/, "", fields[i])
        sub(/[[:space:]]+$/, "", fields[i])
    }
    parsedOrigins++
    if (fields[1] != "com.mfga.xposed") next
    ownOrigins++
    if (fields[2] != "Selffont") {
        otherTags++
        next
    }
    if (!seen[$0]++) {
        count++
        recent[count % 300] = $0
    }
}
END {
    if (count == 0) {
        print "[logs-no-match] No current Selffont origin records; not an injection verdict."
        printf "[logs-format] parsed_origins=%d own_module=%d other_tags=%d\n", parsedOrigins, ownOrigins, otherTags
    } else {
        first = count > 300 ? count - 299 : 1
        for (i = first; i <= count; i++) print recent[i % 300]
    }
}
