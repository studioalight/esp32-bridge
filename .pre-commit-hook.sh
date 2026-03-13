#!/bin/bash
# Pre-commit hook to update GIT_HASH in esp32-bridge.py
# Install: cp .pre-commit-hook.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit

# Get short git hash
HASH=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")

# Update the marker in the file
if [ -f "esp32-bridge.py" ]; then
    sed -i.bak "s/GIT_HASH = \"[^\"]*\"  # GIT_HASH_MARKER/GIT_HASH = \"$HASH\"  # GIT_HASH_MARKER/" esp32-bridge.py
    rm -f esp32-bridge.py.bak
    git add esp32-bridge.py
    echo "Updated GIT_HASH to $HASH"
fi

exit 0
