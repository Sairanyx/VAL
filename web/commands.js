// Runs commands sent to /api/viewer/commands, such as from the voice copilot. See app/api/commands.py.
const POLL_WAIT = 500; // milliseconds

async function report(id, result) {
  await fetch(`/api/viewer/commands/${id}/result`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(result),
  }).catch(() => {});
}

export function setupCommands(handlers) {
  let last = null;

  async function run(command) {
    try {
      const result = await handlers[command.action](command.args);
      await report(command.id, result?.ok === undefined ? { ok: true } : result);
    } catch (error) {
      await report(command.id, { ok: false, message: error.message });
    }
  }

  async function poll() {
    try {
      const query = last === null ? "" : `?after=${last}`;
      const response = await fetch(`/api/viewer/commands${query}`);
      if (response.ok) {
        const data = await response.json();
        // After a backend restart, IDs start again.
        if (last !== null && data.last_id < last) last = data.last_id;
        else {
          for (const command of data.commands) await run(command);
          last = data.last_id;
        }
      }
    } catch {
      // The backend may be restarting, so keep trying.
    }
    setTimeout(poll, POLL_WAIT);
  }
  poll();
}
