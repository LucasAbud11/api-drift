#!/bin/bash
# Reproduces rule_test/scale_experiment/host/ exactly.
#
# The host is NOT committed to this repo (16MB of vendored third-party
# Django source is not worth carrying in git history for a one-off
# experiment) -- run this script to rebuild it byte-for-byte instead.
# Django version pinned below: 5.1.16 alpha, commit 84d09a5.
set -euo pipefail
cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"
REPOS_DIR="$(cd "$SCRIPT_DIR/../../repos" && pwd)"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

git clone --quiet https://github.com/django/django.git "$WORK/django_src"
cd "$WORK/django_src"
git checkout --quiet 84d09a547fe35e10018ab242602ca76c29ca91a1

rm -rf "$SCRIPT_DIR/host"
mkdir -p "$SCRIPT_DIR/host/django"

SRC=django
for d in core template forms http middleware templatetags test urls utils views apps dispatch; do
  cp -R "$SRC/$d" "$SCRIPT_DIR/host/django/$d"
done
mkdir -p "$SCRIPT_DIR/host/django/conf"
cp -R "$SRC/conf/locale" "$SCRIPT_DIR/host/django/conf/locale"
cp "$SRC/conf/__init__.py" "$SCRIPT_DIR/host/django/conf/__init__.py"
cp "$SRC/conf/global_settings.py" "$SCRIPT_DIR/host/django/conf/global_settings.py"
mkdir -p "$SCRIPT_DIR/host/django/contrib"
for d in auth contenttypes sessions messages staticfiles; do
  cp -R "$SRC/contrib/$d" "$SCRIPT_DIR/host/django/contrib/$d"
done
cp "$SRC/__init__.py" "$SCRIPT_DIR/host/django/__init__.py"
cp "$SRC/shortcuts.py" "$SCRIPT_DIR/host/django/shortcuts.py"
cp "$SRC/__main__.py" "$SCRIPT_DIR/host/django/__main__.py"

cd "$SCRIPT_DIR"
mkdir -p host/integrations
for r in tonyzorin_youtrack-mcp QAInsights_jmeter-mcp-server securityfortech_secops-mcp m0xai_trello-mcp-server danilop_MCP2Lambda; do
  cp -R "$REPOS_DIR/$r" "host/integrations/$r"
  rm -rf "host/integrations/$r/.git"
done

# Target A repos, added for the blind_vocab_experiment's diluted Target A run
# (rule_test/blind_vocab_experiment/report.md) -- reuses this same host.
mkdir -p host/integrations_openai
for r in TomaszRewak_MAGI franalgaba_chatgpt-telegram-bot-serverless batuhantoker_Flask-OpenAI-Chatbot g0ldencybersec_sus_params; do
  cp -R "$REPOS_DIR/$r" "host/integrations_openai/$r"
  rm -rf "host/integrations_openai/$r/.git"
done

echo "Host rebuilt: $(find host -name '*.py' | wc -l) files, $(find host -name '*.py' -exec cat {} + | wc -l) LOC"
echo "Decoy check (should print a line): $(grep -n '^class Context' host/django/template/context.py)"
