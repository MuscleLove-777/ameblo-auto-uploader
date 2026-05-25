#!/bin/bash
# GitHub Secrets setup script for MuscleLove-777/ameblo-auto-uploader
# Run this after the repo has been created on GitHub.

GH="/c/Program Files/GitHub CLI/gh"
REPO="MuscleLove-777/ameblo-auto-uploader"
BASE64_FILE="c:/Users/atsus/000_ClaudeCode/004_MuscleLove/001_集客/ameblo-auto-uploader/ameblo_cookies_base64.txt"

echo "Setting AMEBLO_COOKIES secret..."
"$GH" secret set AMEBLO_COOKIES --repo "$REPO" < "$BASE64_FILE"

echo "Setting GDRIVE_FOLDER_ID_AMEBLO secret..."
"$GH" secret set GDRIVE_FOLDER_ID_AMEBLO --repo "$REPO" --body "${GDRIVE_FOLDER_ID_AMEBLO:?Error: GDRIVE_FOLDER_ID_AMEBLO is not set}"

echo "Done. Verifying secrets list..."
"$GH" secret list --repo "$REPO"
