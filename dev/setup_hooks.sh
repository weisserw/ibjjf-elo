#!/bin/sh

cat <<"EOM" > .git/hooks/pre-push
#!/bin/sh

dev/format_python.sh --check && dev/check_python.sh
EOM

chmod +x .git/hooks/pre-push