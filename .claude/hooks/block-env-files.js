#!/usr/bin/env node
let data = '';
process.stdin.on('data', chunk => (data += chunk));
process.stdin.on('end', () => {
  try {
    const input = JSON.parse(data);
    const toolName = input.tool_name || '';
    const toolInput = input.tool_input || {};

    // Safe suffixes that are explicitly allowed (.env.example, .env.sample, etc.)
    // Anchored with $ so .env.example2 / .env.test.local do not slip through.
    const SAFE = /\.env\.(example|sample|template|test)$/i;
    // Matches .env not followed by a word char (avoids .environments, .envelopes, etc.)
    const ENV_RE = /\.env(?![a-zA-Z0-9_])(\.[^\s"'|;&><]*)?/g;

    let blocked = false;

    if (toolName === 'Bash' || toolName === 'PowerShell') {
      // Carve-out: strip quoted commit messages (-m/-am/--message; space or =
      // form; single/double quotes; PowerShell @'...'@ / @"..."@ here-strings;
      // multiline) so mentioning ".env" in a commit message is not blocked.
      // Only these flags are stripped — other quoted strings (e.g.
      // bash -c "cat .env") are still scanned. Interpolating forms (double
      // quotes / @"..."@) are stripped ONLY when free of $ and backticks, so
      // `git commit -m "$(cat .env)"` is still caught.
      const FLAG = '(?:^|\\s)(?:--message|-am|-m)';
      const cmd = String(toolInput.command || '')
        .replace(new RegExp(FLAG + "\\s+@'[\\s\\S]*?'@", 'g'), ' ')
        .replace(new RegExp(FLAG + '\\s+@"(?:(?!["$`])[\\s\\S])*"@', 'g'), ' ')
        .replace(new RegExp(FLAG + "(?:\\s+|=)'[^']*'", 'g'), ' ')
        .replace(new RegExp(FLAG + '(?:\\s+|=)"(?:(?!["$`])[\\s\\S])*"', 'g'), ' ');
      let m;
      while ((m = ENV_RE.exec(cmd)) !== null) {
        if (!SAFE.test(m[0])) {
          blocked = true;
          break;
        }
      }
    } else if (toolName === 'Grep') {
      // Check both the path argument (directory/file being searched) and the
      // glob/pattern args — a pattern like "\.env" targeting a .env file or
      // a path pointing directly at one should both be caught.
      const paths = [toolInput.path, toolInput.file_path].filter(Boolean).map(String);
      const globs  = [toolInput.glob].filter(Boolean).map(String);
      const pathBlocked = paths.some(
        v => /[/\\]?\.env(?![a-zA-Z0-9_])(\.[^./\\]*)?$/.test(v) && !SAFE.test(v)
      );
      // Block Grep patterns that directly target a .env file name/path
      const globBlocked = globs.some(
        v => /\.env(?![a-zA-Z0-9_])/.test(v) && !SAFE.test(v)
      );
      blocked = pathBlocked || globBlocked;
    } else {
      // Read, Write, Edit, Glob — check file path fields
      const paths = [toolInput.file_path, toolInput.path].filter(Boolean).map(String);
      blocked = paths.some(
        v => /[/\\]?\.env(?![a-zA-Z0-9_])(\.[^./\\]*)?$/.test(v) && !SAFE.test(v)
      );
    }

    if (blocked) {
      process.stdout.write(
        JSON.stringify({
          hookSpecificOutput: {
            hookEventName: 'PreToolUse',
            permissionDecision: 'deny',
            permissionDecisionReason:
              '.env files are off-limits. Reference .env.example instead.',
          },
        })
      );
    }
    process.exit(0);
  } catch {
    // Fail-closed on malformed hook input: deny the tool use rather than silently
    // allowing it, so a crafted or truncated payload cannot bypass this hook.
    process.stdout.write(
      JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: 'deny',
          permissionDecisionReason:
            'block-env-files hook received malformed input; denying as a precaution.',
        },
      })
    );
    process.exit(0);
  }
});
