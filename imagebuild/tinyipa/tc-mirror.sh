
#NOTE(pas-ha)
# The first URL is the official TC repo,
# the rest of the list is taken from
# http://wiki.tinycorelinux.net/wiki:mirrors
# as of time of this writing.
# Only HTTP mirrors were considered with the following ordering
# - those that were unavailable are moved to the bottom of the list
# - those that already responded with 404 are moved to the very bottom

# List generated on 12-Dec-2016
TC_MIRRORS="http://repo.tinycorelinux.net
http://distro.ibiblio.org/tinycorelinux
http://mirror.cedia.org.ec/tinycorelinux
http://mirror.epn.edu.ec/tinycorelinux
http://mirrors.163.com/tinycorelinux
http://kambing.ui.ac.id/tinycorelinux
http://ftp.nluug.nl/os/Linux/distr/tinycorelinux
http://ftp.vim.org/os/Linux/distr/tinycorelinux
http://www.gtlib.gatech.edu/pub/tinycore
http://tinycore.mirror.uber.com.au
http://l4u-00.jinr.ru/LinuxArchive/Ftp/tinycorelinux"

function probe_url {
    wget -q --spider --tries 1 --timeout 10 "$1" 2>&1
}

function choose_tc_mirror {
    if [ -z ${TINYCORE_MIRROR_URL} ]; then
        for url in ${TC_MIRRORS}; do
            echo "Checking Tiny Core Linux mirror ${url}"
            if probe_url ${url} ; then
                echo "Check succeeded: ${url} is responding."
                TINYCORE_MIRROR_URL=${url}
                break
            else
                echo "Check failed: ${url} is not responding"
            fi
        done
        if [ -z ${TINYCORE_MIRROR_URL} ]; then
            echo "Failed to find working Tiny Core Linux mirror"
            exit 1
        fi
    else
        echo "Probing provided Tiny Core Linux mirror ${TINYCORE_MIRROR_URL}"
        if probe_url ${TINYCORE_MIRROR_URL} ; then
            echo "Check succeeded: ${TINYCORE_MIRROR_URL} is responding."
        else
            echo "Check failed: ${TINYCORE_MIRROR_URL} is not responding"
            exit 1
        fi
    fi
}
