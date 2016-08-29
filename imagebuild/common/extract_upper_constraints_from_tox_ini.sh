#!/bin/bash
# NOTE(mmitchell): This extracts the URL defined as the default value for
#                  UPPER_CONSTRAINTS_FILE in tox.ini. This is used by image
#                  builders to avoid duplicating the default value in multiple
#                  scripts. This is specially done to leverage the release
#                  tools that automatically update the tox.ini when projects
#                  are released.
sed -n 's/^.*{env:UPPER_CONSTRAINTS_FILE\:\([^}]*\)}.*$/\1/p' $1 | head -n1

