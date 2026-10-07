# erasewitness README demo. Real run against Mem0 OSS 2.2.1 with real Jev and
# OpenAI judges. Nothing is mocked. Waiting time while the run executes is cut.

Output demo/erasewitness.gif

Set Shell "bash"
Set FontSize 18
Set Width 1500
Set Height 820
Set Padding 20
Set WindowBar Colorful
Set CursorBlink false
Set TypingSpeed 45ms
Set Theme "Catppuccin Frappe"

Hide
Type "source $EW_KEYS && export PATH=$PWD/.venv/bin:$PATH HOME=/tmp/ew-demo-home PS1='$ ' && rm -rf /tmp/ew-demo /tmp/ew-demo-home && mkdir -p /tmp/ew-demo-home && clear" Enter
Sleep 1s
Show

Type "# plant a fake salary in Mem0, delete it, then look for it"
Sleep 800ms
Enter
Type "erasewitness run --target mem0 --scenario salary --judges jev,openai --out /tmp/ew-demo 2>/dev/null"
Sleep 500ms
Enter
Hide
Sleep 240s
Show
Sleep 3s

Type "# where did the deleted salary survive?"
Enter
Type `jq -r '.after[] | select(.verdict=="LEAKED") | .source[0:12] + "  " + .text[0:60]' /tmp/ew-demo/*/evidence/derived.json | sort -u -k2 | head -5`
Sleep 500ms
Enter
Sleep 4s

Type "erasewitness verify /tmp/ew-demo/*/ | head -1"
Sleep 500ms
Enter
Sleep 5s
