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
    // Matches the .env DOTFILE: not preceded by a word char (avoids member
    // access like process.env.X / os.environ, and foo.env files — the secret
    // file convention here is the bare dotfile) and not followed by a word
    // char (avoids .environments, .envelopes, etc.).
    const ENV_RE = /(?<![a-zA-Z0-9_])\.env(?![a-zA-Z0-9_])(\.[^\s"'|;&><]*)?/g;

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
    } else {
      // Read, Write, Edit, Glob, Grep — check file path fields
      // Known gap: only file_path/path are checked; a Grep content search over
      // a directory can still surface .env lines in its results.
      const paths = [toolInput.file_path, toolInput.path].filter(Boolean).map(String);
      blocked = paths.some(
        v =>
          /(?<![a-zA-Z0-9_])\.env(?![a-zA-Z0-9_])(\.[^./\\]*)?$/.test(v) &&
          !SAFE.test(v)
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
    // Deliberate fail-open: a hook crash on malformed input must not brick all tool use.
    process.exit(0);
  }
});
