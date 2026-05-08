Output docs/demo.gif

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
Type "alias gpr=/Users/aditya/Developer/gpr/bin/gpr"
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
Type "python3 /Users/aditya/Developer/gpr/docs/seed-demo-plan.py"
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
