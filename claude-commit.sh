#!/bin/bash
# Shell function for automated Claude Code commits
# Add this to your .bashrc or .zshrc:
# source /path/to/claude-commit.sh

claude-commit() {
    if [ -z "$1" ]; then
        echo "Usage: claude-commit 'Your commit message'"
        return 1
    fi
    
    git add -A
    git commit -m "$(cat <<EOF
$1

🤖 Generated with [Claude Code](https://claude.ai/code)

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
}

# Usage examples:
# claude-commit "Fix input validation bug"
# claude-commit "Add new debug features for Knox integration"