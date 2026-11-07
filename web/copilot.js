// Copilot panel: ask about the selected object, and show the answer with its evidence.

function row(parent, tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  parent.append(element);
  return element;
}

function section(parent, title, items) {
  if (!items?.length) return;
  row(parent, "h3", title);
  const list = document.createElement("ul");
  for (const item of items) row(list, "li", item);
  parent.append(list);
}

export function setupCopilot({ panel, form, input, answer, close, getObject }) {
  async function ask(question) {
    const object = getObject();
    answer.replaceChildren();
    row(answer, "p", "Thinking...");
    let reply;
    try {
      const response = await fetch("/api/copilot/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, object_id: object?.asset.object_id ?? null }),
      });
      reply = await response.json();
      if (!response.ok) throw new Error(reply.detail ?? `Backend error ${response.status}`);
    } catch (error) {
      answer.replaceChildren();
      row(answer, "p", `The copilot couldn't answer: ${error.message}`, "warning");
      return;
    }
    answer.replaceChildren();
    if (reply.placeholder) row(answer, "p", "Placeholder: the copilot isn't connected.", "warning");
    if (reply.safety_passed === false) row(answer, "p", "Refused for safety.", "warning");
    row(answer, "p", reply.answer);
    section(answer, "Observed", reply.observations);
    section(answer, "Possible causes", reply.hypotheses);
    section(answer, "Sources", reply.citations);
    const mapping = object?.asset.mapping;
    const notes = [`Answer confidence ${Number(reply.confidence ?? 0).toFixed(2)}`];
    if (mapping) {
      notes.push(`Object linked to ${mapping.tag} by ${mapping.method}, ${mapping.confidence}`);
    }
    row(answer, "p", notes.join(" · "), "note");
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (input.value.trim()) ask(input.value.trim());
  });
  close.onclick = () => (panel.hidden = true);

  return {
    open(question) {
      panel.hidden = false;
      if (question) {
        input.value = question;
        ask(question);
      }
    },
  };
}
