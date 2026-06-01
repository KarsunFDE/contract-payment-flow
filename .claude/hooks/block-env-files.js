#!/usr/bin/env node
let data = '';
process.stdin.on('data', chunk => (data += chunk));
process.stdin.on('end', () => {
  try {
    const input = JSON.parse(data);
    const toolInput = input.tool_input || {};

    // Collect every string field that could carry a file path or command
    const candidates = [
      toolInput.file_path,
      toolInput.path,
      toolInput.command,
      toolInput.old_string,
      toolInput.new_string,
    ]
      .filter(Boolean)
      .map(String);

    const isEnvFile = candidates.some(
      v =>
        /[/\\]?\.env(\.[^.]+)?$/.test(v) &&
        !/\.(example|sample|template|test)$/.test(v)
    );

    if (isEnvFile) {
      console.log(
        JSON.stringify({
          decision: 'block',
          reason:
            '.env files are off-limits. Reference .env.example instead.',
        })
      );
    }
    process.exit(0);
  } catch {
    process.exit(0);
  }
});
