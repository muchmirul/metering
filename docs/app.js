(() => {
  "use strict";

  const board = document.querySelector("#candidate-board");
  if (!board) return;

  const stages = [
    {
      kicker: "Before action 1",
      title: "The controller chooses a fault",
      detail: "All eight identifiers remain possible in the public view. The policy gets the same catalogue no matter which fault was selected.",
      action: "None yet",
      observation: "None yet",
      privateNote: "Only the controller holds the selected fault and private commitment nonce.",
      candidates: ["fault-0", "fault-1", "fault-2", "fault-3", "fault-4", "fault-5", "fault-6", "fault-7"],
      history: "No observations yet",
      diagnostics: 0,
      actions: 0,
      selected: false,
    },
    {
      kicker: "Action 1 · first even split",
      title: "Ask whether split 1 is positive",
      detail: "This public test is positive for faults 1, 3, 5, and 7. The delivered positive result removes the other four candidates.",
      action: 'Diagnose("split-1")',
      observation: "positive: true",
      privateNote: "The observation comes from the hidden world. The selected fault itself still does not cross the callback boundary.",
      candidates: ["fault-1", "fault-3", "fault-5", "fault-7"],
      history: "split-1 → positive",
      diagnostics: 1,
      actions: 1,
      selected: false,
    },
    {
      kicker: "Action 2 · second even split",
      title: "Ask whether split 2 is positive",
      detail: "Among the four remaining candidates, a negative result rules out faults 3 and 7. Faults 1 and 5 still agree with the public history.",
      action: 'Diagnose("split-2")',
      observation: "positive: false",
      privateNote: "Only delivered diagnostic results shrink the candidate set. Merely choosing a test would not count as evidence.",
      candidates: ["fault-1", "fault-5"],
      history: "split-1 → positive · split-2 → negative",
      diagnostics: 2,
      actions: 2,
      selected: false,
    },
    {
      kicker: "Action 3 · final even split",
      title: "Ask whether split 3 is positive",
      detail: "A positive result separates the last pair. Only fault 5 remains consistent with all three delivered results.",
      action: 'Diagnose("split-3")',
      observation: "positive: true",
      privateNote: "The report will count three diagnostic observations and three bits of uncertainty removed for this run.",
      candidates: ["fault-5"],
      history: "split-1 → positive · split-2 → negative · split-3 → positive",
      diagnostics: 3,
      actions: 3,
      selected: false,
    },
    {
      kicker: "Action 4 · choose a repair",
      title: "Repair the only remaining candidate",
      detail: "The world records fault 5 as the current proposed repair. The response acknowledges which repair was applied, but does not say whether it is correct.",
      action: 'Repair("fault-5")',
      observation: "repair applied: fault-5",
      privateNote: "The controller can compare the proposal with private truth later. Correctness is not delivered to the policy here.",
      candidates: ["fault-5"],
      history: "3 diagnostic results · repair applied",
      diagnostics: 3,
      actions: 4,
      selected: true,
    },
    {
      kicker: "Action 5 · verify",
      title: "Verification acknowledges the act, not the answer",
      detail: "The policy receives the same content-free acknowledgement whether its repair matches or not. It cannot use verification as another hidden-state test.",
      action: "Verify()",
      observation: "verification acknowledged",
      privateNote: "Pass or fail is stored only in controller-private state until offline reporting. A later repair would make this verification stale.",
      candidates: ["fault-5"],
      history: "3 diagnostic results · repair applied · verification acknowledged",
      diagnostics: 3,
      actions: 5,
      selected: true,
    },
    {
      kicker: "Action 6 · finish, then report",
      title: "Finish execution and measure offline",
      detail: "A valid finish ends the action loop. The offline verifier replays the bound artifacts and reports the four correctness facts separately.",
      action: "Finish()",
      observation: "finish accepted",
      privateNote: "For this example, the final repair matches, verification followed it, finish was normal, and the budget was respected.",
      candidates: ["fault-5"],
      history: "run finished normally after 6 actions",
      diagnostics: 3,
      actions: 6,
      selected: true,
    },
  ];

  const elements = {
    count: document.querySelector("#candidate-count"),
    history: document.querySelector("#history-value"),
    kicker: document.querySelector("#stage-kicker"),
    title: document.querySelector("#stage-title"),
    detail: document.querySelector("#stage-detail"),
    action: document.querySelector("#stage-action"),
    observation: document.querySelector("#stage-observation"),
    privateNote: document.querySelector("#stage-private"),
    diagnostics: document.querySelector("#metric-diagnostics"),
    actions: document.querySelector("#metric-actions"),
    previous: document.querySelector("#previous-step"),
    next: document.querySelector("#next-step"),
    dots: Array.from(document.querySelectorAll("[data-step]")),
    candidates: Array.from(board.querySelectorAll("[data-fault]")),
  };

  let current = 0;

  function render(index, moveFocus = false) {
    current = Math.max(0, Math.min(stages.length - 1, index));
    const stage = stages[current];
    const possible = new Set(stage.candidates);

    elements.kicker.textContent = stage.kicker;
    elements.title.textContent = stage.title;
    elements.detail.textContent = stage.detail;
    elements.action.textContent = stage.action;
    elements.observation.textContent = stage.observation;
    elements.privateNote.textContent = stage.privateNote;
    elements.history.textContent = stage.history;
    elements.diagnostics.textContent = String(stage.diagnostics);
    elements.actions.textContent = String(stage.actions);
    elements.count.textContent = `${stage.candidates.length} ${stage.candidates.length === 1 ? "remains" : "remain"}`;

    elements.candidates.forEach((candidate) => {
      const fault = candidate.dataset.fault;
      const isPossible = possible.has(fault);
      const isSelected = stage.selected && fault === "fault-5";
      const status = candidate.querySelector(".candidate-status");

      candidate.classList.toggle("is-possible", isPossible && !isSelected);
      candidate.classList.toggle("is-eliminated", !isPossible);
      candidate.classList.toggle("is-selected", isSelected);
      candidate.setAttribute("aria-label", `${fault}, ${isSelected ? "selected repair" : isPossible ? "still possible" : "eliminated"}`);
      status.textContent = isSelected ? "selected repair" : isPossible ? "possible" : "eliminated";
    });

    elements.previous.disabled = current === 0;
    elements.next.disabled = current === stages.length - 1;
    elements.next.innerHTML = current === stages.length - 1
      ? "Complete"
      : 'Next <span aria-hidden="true">→</span>';

    elements.dots.forEach((button, dotIndex) => {
      if (dotIndex === current) {
        button.setAttribute("aria-current", "step");
      } else {
        button.removeAttribute("aria-current");
      }
    });

    if (moveFocus) {
      elements.title.setAttribute("tabindex", "-1");
      elements.title.focus({ preventScroll: true });
    }
  }

  elements.previous.addEventListener("click", () => render(current - 1));
  elements.next.addEventListener("click", () => {
    if (current < stages.length - 1) render(current + 1);
  });

  elements.dots.forEach((button) => {
    button.addEventListener("click", () => render(Number(button.dataset.step)));
  });

  document.addEventListener("keydown", (event) => {
    const active = document.activeElement;
    if (!active || !active.closest || !active.closest(".example-shell")) return;
    if (event.key === "ArrowLeft" && current > 0) {
      event.preventDefault();
      render(current - 1);
    }
    if (event.key === "ArrowRight" && current < stages.length - 1) {
      event.preventDefault();
      render(current + 1);
    }
  });

  render(0);
})();
