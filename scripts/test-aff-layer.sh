#!/usr/bin/env bash
# Regression test for the affiliate layer's fail-safe behaviour.
# Verifies the four states that matter, then restores a clean tree.
set -u
export PATH=$HOME/.local/bin:$PATH
cd ~/projects/devtool-digest

TEST=content/posts/zzafftest.md
cp data/partners.toml /tmp/p.bak
pass=0; fail=0
chk() { # chk <label> <actual> <expected>
  if [ "$2" = "$3" ]; then echo "  PASS  $1 ($2)"; pass=$((pass+1));
  else echo "  FAIL  $1 — got '$2' expected '$3'"; fail=$((fail+1)); fi
}

printf '%s\n' '---' 'title: "Aff Test"' 'date: 2026-09-21T06:00:00+02:00' 'draft: false' '---' \
  'A {{< aff cloudways >}}Cloudways{{< /aff >}} and {{< aff kinsta "Kinsta" />}}.' \
  'Repeat {{< aff cloudways >}}again{{< /aff >}} — disclosure must not duplicate.' > $TEST

F=public/posts/zzafftest/index.html

echo "STATE 1 — not enrolled: plain links, no disclosure, no sponsored rel"
hugo --gc --minify --quiet 2>/dev/null
chk "disclosure blocks" "$(grep -o 'aff-disclosure' $F | wc -l | tr -d ' ')" "0"
chk "sponsored rels"    "$(grep -o 'sponsored' $F | wc -l | tr -d ' ')" "0"
chk "aff marks"         "$(grep -o 'aff-mark' $F | wc -l | tr -d ' ')" "0"
chk "plain links"       "$(grep -o 'class=aff-link' $F | wc -l | tr -d ' ')" "3"

echo "STATE 2 — unknown partner key: build must fail"
sed -i 's/aff kinsta "Kinsta" \//aff nosuchvendor "X" \//' $TEST
hugo --gc --minify >/dev/null 2>&1
chk "build rejects typo" "$?" "1"
sed -i 's/aff nosuchvendor "X" \//aff kinsta "Kinsta" \//' $TEST

echo "STATE 3 — enrolled: disclosure once, sponsored rel, id in URL"
sed -i '0,/id            = ""/s//id            = "TESTID123"/' data/partners.toml
hugo --gc --minify --quiet 2>/dev/null
chk "disclosure once"   "$(grep -o 'aff-disclosure' $F | wc -l | tr -d ' ')" "1"
chk "sponsored rels"    "$(grep -o 'sponsored' $F | wc -l | tr -d ' ')" "2"
chk "aff marks"         "$(grep -o 'aff-mark' $F | wc -l | tr -d ' ')" "2"
chk "id substituted"    "$(grep -o 'id=TESTID123' $F | wc -l | tr -d ' ')" "2"
chk "unenrolled stays plain" "$(grep -oE 'href=https://kinsta.com/ rel=noopener' $F | wc -l | tr -d ' ')" "1"
chk "partner table row" "$(grep -o '<strong>Cloudways</strong>' public/disclosure/index.html | wc -l | tr -d ' ')" "1"

echo "STATE 4 — raw tracking link bypassing shortcode: audit must fail"
printf '\n[Cloudways](https://www.cloudways.com/en/?id=BYPASS) raw.\n' >> $TEST
python3 scripts/audit-links.py >/dev/null 2>&1
chk "audit blocks bypass" "$?" "1"

cp /tmp/p.bak data/partners.toml; rm -f $TEST /tmp/p.bak
rm -rf public; hugo --gc --minify --quiet 2>/dev/null
python3 scripts/audit-links.py >/dev/null 2>&1
chk "clean tree audits clean" "$?" "0"

echo
echo "$pass passed, $fail failed"
[ $fail -eq 0 ]
