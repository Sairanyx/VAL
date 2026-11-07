// Val: ask about the room or the selected object, and see each answer with its evidence.

function make(tag, text, className) {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
}

function evidenceList(parent, title, items) {
  if (!items?.length) return;
  parent.append(make("h4", title));
  const list = make("ul");
  for (const item of items) list.append(make("li", item));
  parent.append(list);
}

// Spoken by the device's own voice, which works offline if a voice is installed.
function speak(text) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

function suggestionsFor(object, nameOf, faultTag) {
  if (!object) {
    return ["What needs attention?", `Take me to ${faultTag}`, `What's wrong with ${faultTag}?`];
  }
  if (!object.asset.mapping) return ["What is this?", "Take me there"];
  return [
    "What's wrong with it?",
    "What should I check first?",
    "When was it last serviced?",
    "Take me there",
  ];
}

export function setupCopilot({
  panel,
  form,
  input,
  messages,
  suggestions,
  context,
  close,
  speakButton,
  getObject,
  clearObject,
  nameOf,
  getFaultTag,
  onActions,
}) {
  let speaking = true;
  let waiting = false;
  speakButton.onclick = () => {
    speaking = !speaking;
    speakButton.textContent = speaking ? "Voice on" : "Voice off";
    if (!speaking) window.speechSynthesis?.cancel();
  };

  function scrollDown() {
    messages.scrollTop = messages.scrollHeight;
  }

  function say(text, className) {
    const bubble = make("div", undefined, `bubble val ${className ?? ""}`);
    bubble.append(make("p", text));
    messages.append(bubble);
    scrollDown();
    return bubble;
  }

  function refresh() {
    const object = getObject();
    context.replaceChildren();
    if (object) {
      context.append(`About ${nameOf(object)}`);
      const clear = make("button", "×", "clear-context");
      clear.type = "button";
      clear.setAttribute("aria-label", "Stop asking about this object");
      clear.onclick = () => {
        clearObject();
        refresh();
      };
      context.append(clear);
    } else context.append("About the whole room");
    suggestions.replaceChildren();
    for (const question of suggestionsFor(object, nameOf, getFaultTag())) {
      const chip = make("button", question, "chip");
      chip.type = "button";
      chip.onclick = () => ask(question);
      suggestions.append(chip);
    }
  }

  function showAnswer(reply, object, bubble = say("")) {
    bubble.className = `bubble val ${reply.placeholder || reply.safety_passed === false ? "warning" : ""}`;
    bubble.replaceChildren(make("p", reply.answer));
    if (reply.placeholder) return bubble;
    const mapping = object?.asset.mapping;
    const unsure = mapping && !nameOf(object).endsWith(mapping.tag);
    if (unsure) {
      bubble.append(make("p", `The link to ${mapping.tag} isn't confirmed.`, "unsure"));
    }
    if (reply.citations?.length) {
      bubble.append(make("p", `Sources: ${reply.citations.join(", ")}`, "sources"));
    }
    const details = make("details");
    details.append(make("summary", "How Val knows"));
    evidenceList(details, "Recorded", reply.observations);
    evidenceList(details, "Possible causes, not confirmed", reply.hypotheses);
    const notes = [`Confidence ${Number(reply.confidence ?? 0).toFixed(2)}`];
    notes.push("answer written from the records by code");
    if (mapping) notes.push(`linked to ${mapping.tag} by ${mapping.method}, ${mapping.confidence}`);
    details.append(make("p", notes.join(" · "), "note"));
    bubble.append(details);
    scrollDown();
    return bubble;
  }

  async function query(question, object, quick) {
    const response = await fetch("/api/copilot/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, object_id: object?.asset.object_id ?? null, quick }),
    });
    const reply = await response.json();
    if (!response.ok) throw new Error(reply.detail ?? `Backend error ${response.status}`);
    return reply;
  }

  // The answer from the records comes at once, and stays, as a small model's wording is true but
  // can leave things out. Its plain words are added if and when they arrive and pass the checks.
  async function reword(question, object, bubble) {
    const hint = make("p", "Val is putting this in plain words...", "rewording");
    bubble.append(hint);
    scrollDown();
    try {
      const better = await query(question, object, false);
      if (better.answer_source === "model") {
        const words = better.answer
          .replace(/\s*\[[^\]]*\]/g, "")
          .replace(/\s*Follow site lockout.*$/, "")
          .trim();
        hint.className = "plain-words";
        hint.textContent = `In plain words: ${words}`;
        scrollDown();
      } else hint.remove();
    } catch {
      hint.remove();
    }
  }

  async function ask(question) {
    if (waiting) return;
    waiting = true;
    input.value = "";
    const object = getObject();
    messages.append(make("div", question, "bubble you"));
    const thinking = say("Val is thinking...", "thinking");
    let reply;
    try {
      reply = await query(question, object, true);
    } catch (error) {
      thinking.remove();
      say(`I can't answer right now: ${error.message}`, "warning");
      waiting = false;
      return;
    }
    thinking.remove();
    const bubble = showAnswer(reply, object);
    if (speaking) speak(reply.answer);
    waiting = false;
    const problem = await onActions(reply.actions ?? []);
    if (problem) bubble.append(make("p", problem, "unsure"));
    refresh();
    scrollDown();
    if (reply.can_reword) reword(question, object, bubble);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (input.value.trim()) ask(input.value.trim());
  });
  close.onclick = () => {
    panel.hidden = true;
    window.speechSynthesis?.cancel();
  };

  let greeted = false;
  return {
    refresh,
    open(question) {
      panel.hidden = false;
      if (!greeted) {
        greeted = true;
        say("Hi, I'm Val. Tap a device and ask me about it, or ask what needs attention.");
      }
      refresh();
      if (question) ask(question);
      else if (!document.body.classList.contains("tablet")) input.focus();
    },
  };
}
