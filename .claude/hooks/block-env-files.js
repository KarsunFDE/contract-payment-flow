#!/usr/bin/env node
let data = '';
process.stdin.on('data', chunk => (data += chunk));
process.stdin.on('end', () => {
  try {
    const input = JSON.parse(data);
    const toolName = input.tool_name || '';
    const toolInput = input.tool_input || {};

    // Safe suffixes that are explicitly allowed (.env.example, .env.sample, etc.)
    const SAFE = /\.env\.(example|sample|template|test)/i;
    // Matches .env not followed by a word char (avoids .environments, .envelopes, etc.)
    const ENV_RE = /\.env(?![a-zA-Z0-9_])(\.[^\s"'|;&><]*)?/g;

    let blocked = false;

    if (toolName === 'Bash' || toolName === 'PowerShell') {
      const cmd = String(toolInput.command || '');
      let m;
      while ((m = ENV_RE.exec(cmd)) !== null) {
        if (!SAFE.test(m[0])) {
          blocked = true;
          break;
        }
      }
    } else {
      // Read, Write, Edit, Glob, Grep — check file path fields
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
    process.exit(0);
  }
});
