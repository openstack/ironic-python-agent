#!/bin/bash -eu

SCRIPT_NAME=$(basename $0)
COMMON_ROOT=$(dirname $0)
DESTINATION="$1"
TOX_INI_UPPER_CONSTRAINT_URL="$(${COMMON_ROOT}/extract_upper_constraints_from_tox_ini.sh ${COMMON_ROOT}/../../tox.ini)"

copy() {
    local src=$1
    local destination=$2

    if test -z "${src}"; then
        return 1
    fi

    if test -e "${src}"; then
        log "File '${src}' exists. Using as upper-constraints."
        cp "${src}" "${destination}"
    else
        log "File '${src}' not found. Skipping local file strategy."
        return 1
    fi
    return 0
}

download() {
    local url=$1
    local destination=$2

    if test -z "${url}"; then
        return 1
    else
        log "Downloading from '${url}'"
        curl ${url} -o "${destination}"
    fi
    return 0
}

log() {
    echo "${SCRIPT_NAME}: ${@}"
}

fail() {
    log ${@}
    exit 1
}

upper_constraints_is_not_null() {
    test "${UPPER_CONSTRAINTS_FILE:-""}" != ""
}

copy_uc() {
    copy "${UPPER_CONSTRAINTS_FILE:-""}" "${DESTINATION}"
}

download_uc() {
    download "${UPPER_CONSTRAINTS_FILE:-""}" "${DESTINATION}"
}

copy_new_requirements_uc() {
    copy "/opt/stack/new/requirements/upper-constraints.txt" "${DESTINATION}"
}

download_from_tox_ini_url() {
    log "tox.ini indicates '${TOX_INI_UPPER_CONSTRAINT_URL}' as fallback."
    download "${TOX_INI_UPPER_CONSTRAINT_URL}" "${DESTINATION}"
}

log "Generating local constraints file..."

if upper_constraints_is_not_null; then
    log "UPPER_CONSTRAINTS_FILE is defined as '${UPPER_CONSTRAINTS_FILE:-""}'"
    copy_uc || download_uc || fail "Failed to copy or download file indicated in UPPER_CONSTRAINTS_FILE."
else
    log "UPPER_CONSTRAINTS_FILE is not defined. Using fallback strategies."

    copy_new_requirements_uc || \
    download_from_tox_ini_url || fail "Failed to download upper-constraints.txt from '${TOX_INI_UPPER_CONSTRAINT_URL}'."
fi
