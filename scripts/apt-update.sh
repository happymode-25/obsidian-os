#!/bin/sh
# debos: refresh apt lists. Called right after the overlay unpack brings the
# local /obsrepo source (etc/apt/sources.list.d/obsidian-local.list) into the
# target, so subsequent apt actions can resolve obsidian-* metapackages.
set -eu
apt-get update