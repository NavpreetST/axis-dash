Pre-push checklist:
  1. npm run lint && npm run test
  2. grep -n 'uses:.*@v[0-9]' .github/workflows/*.yml | grep -v '# pinned'
     — pin any found before push
Post-push:
  Poll until all gates green + CodeRabbit not CHANGES_REQUESTED.
  Only then report "ready for merge."
