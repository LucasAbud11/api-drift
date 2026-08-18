#!/bin/bash
# Reproduces rule_test/scale_experiment/host/ exactly.
#
# The host is NOT committed to this repo (16MB of vendored third-party
# Django source is not worth carrying in git history for a one-off
# experiment) -- run this script to rebuild it byte-for-byte instead.
# Django version pinned below: 5.1.16 alpha, commit 84d09a5.
set -euo pipefail
cd "$(dirname "$0")"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

git clone --quiet https://github.com/django/django.git "$WORK/django_src"
cd "$WORK/django_src"
git checkout --quiet 84d09a547fe35e10018ab242602ca76c29ca91a1

rm -rf ../../host
mkdir -p ../../host/django

SRC=django
for d in core template forms http middleware templatetags test urls utils views apps dispatch; do
  cp -R "$SRC/$d" "../../host/django/$d"
done
mkdir -p ../../host/django/conf
cp -R "$SRC/conf/locale" ../../host/django/conf/locale
cp "$SRC/conf/__init__.py" ../../host/django/conf/__init__.py
cp "$SRC/conf/global_settings.py" ../../host/django/conf/global_settings.py
mkdir -p ../../host/django/contrib
for d in auth contenttypes sessions messages staticfiles; do
  cp -R "$SRC/contrib/$d" "../../host/django/contrib/$d"
done
cp "$SRC/__init__.py" ../../host/django/__init__.py
cp "$SRC/shortcuts.py" ../../host/django/shortcuts.py
cp "$SRC/__main__.py" ../../host/django/__main__.py

cd ../../
mkdir -p host/integrations
for r in tonyzorin_youtrack-mcp QAInsights_jmeter-mcp-server securityfortech_secops-mcp m0xai_trello-mcp-server danilop_MCP2Lambda; do
  cp -R "../../repos/$r" "host/integrations/$r"
  rm -rf "host/integrations/$r/.git"
done

echo "Host rebuilt: $(find host -name '*.py' | wc -l) files, $(find host -name '*.py' -exec cat {} + | wc -l) LOC"
echo "Decoy check (should print a line): $(grep -n '^class Context' host/django/template/context.py)"
