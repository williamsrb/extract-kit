#!/bin/bash

# Script to filter ID entries by NAME and return the matching ID
# Usage: ./filter-by-name.sh "NAME_TO_SEARCH"

NAME_TO_SEARCH="$1"

if [[ -z "$NAME_TO_SEARCH" ]]; then
    echo "Error: Please provide a name to search for"
    echo "Usage: $0 \"NAME_TO_SEARCH\""
    exit 1
fi

# Read from stdin and filter by name
awk -v search="$NAME_TO_SEARCH" '
NR == 1 {
    # Find the column position where "NAME" starts in the header
    col_pos = index($0, "NAME")
    next
}
{
    id = substr($0, 1, col_pos - 1)
    name = substr($0, col_pos)
    gsub(/[[:space:]]+$/, "", id)
    gsub(/^[[:space:]]+/, "", name)
    if (index(name, search) > 0) {
        print id
        found = 1
    }
}
END {
    if (!found) {
        print "Error: No entry found with name containing \"" search "\"" > "/dev/stderr"
        exit 1
    }
}
'
