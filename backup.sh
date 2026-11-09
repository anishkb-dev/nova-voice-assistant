#!/bin/zsh
# Nightly (launchd com.nova.backup): auto-commit ~/anish-ai locally, then copy the whole git history
# to the Helumi drive as one bundle. Restore: git clone /Volumes/Helumi/nova-backup/anish-ai.bundle anish-ai
# Never pushes to GitHub (that repo is PUBLIC). Secrets stay out via .gitignore + the guard below.
cd ~/anish-ai || exit 1
LOG=/tmp/nova-backup.log
ID=(-c user.name="$(git log -1 --format=%an)" -c user.email="$(git log -1 --format=%ae)")
git add -A
BAD=$(git diff --cached --name-only | grep -iE '_key|secret|token|\.env|\.pem|\.npy' | grep -v 'secrets\.h\.example')
if [ -n "$BAD" ]; then
  echo "$(date '+%F %T') REFUSED: secret-looking file staged: $BAD" >> $LOG
  git reset -q; exit 1
fi
git diff --cached --quiet || git $ID commit -qm "auto backup $(date +%F)"
D=/Volumes/Helumi/nova-backup
if [ ! -d /Volumes/Helumi ]; then echo "$(date '+%F %T') Helumi not mounted; committed locally only" >> $LOG; exit 0; fi
mkdir -p $D
git bundle create $D/anish-ai.bundle.tmp --all 2>>$LOG \
  && mv $D/anish-ai.bundle.tmp $D/anish-ai.bundle \
  && echo "$(date '+%F %T') ok $(git log --oneline -1)" >> $LOG
