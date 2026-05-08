Output docs/demo.gif

# Regenerate this recording with:
#   GPR_HOME=$(git rev-parse --show-toplevel) vhs docs/demo.tape
# (so the tape is portable across contributors)

Set Shell zsh
Set FontSize 14
Set Width 1280
Set Height 760
Set Padding 24
Set Theme "Dracula"
Set TypingSpeed 32ms

Hide
Type "cd /tmp && rm -rf demo-gpr && mkdir demo-gpr && cd demo-gpr && git init -q -b main"
Enter
Type "alias gpr=$GPR_HOME/bin/gpr"
Enter
Type "clear"
Enter
Show

Type "gpr"
Enter
Sleep 3s

Type 'gpr init --objective "Build a TODO REST API with auth"'
Enter
Sleep 1500ms

Hide
Type "python3 $GPR_HOME/docs/seed-demo-plan.py"
Enter
Type "clear"
Enter
Show

Type "gpr status"
Enter
Sleep 4s

Type "gpr lint"
Enter
Sleep 3s

Type "gpr doctor"
Enter
Sleep 3s
