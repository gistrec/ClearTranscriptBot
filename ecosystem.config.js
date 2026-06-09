module.exports = {
  apps: [
    {
      name: "clear-transcript-bot",
      script: "main.py",
      interpreter: "./venv/bin/python",
      cwd: "/home/gistrec/ClearTranscriptBot",
      autorestart: true,
      // Exponential backoff between restarts: 100ms, 200ms, 400ms ...
      // pm2 caps the delay at 15000ms, so restarts settle at one attempt / 15s.
      exp_backoff_restart_delay: 100,
      // Keep retrying indefinitely instead of giving up after the default 16.
      max_restarts: Number.MAX_SAFE_INTEGER,
    },
  ],
};
