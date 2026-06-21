document.querySelectorAll("[data-edit]").forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.target;
    const form = document.querySelector(`[data-edit-form="${target}"]`);
    const payload = JSON.parse(button.dataset.edit);
    if (!form) return;

    Object.entries(payload).forEach(([key, value]) => {
      const field = form.elements.namedItem(key);
      if (field) {
        field.value = value ?? "";
      }
    });

    if (target === "evaluation") {
      const status = form.elements.namedItem("satisfied");
      if (status) status.value = String(payload.satisfied);
    }

    if (target === "task") {
      const status = form.elements.namedItem("satisfied");
      if (status) status.value = String(payload.satisfied);
    }

    form.closest("details")?.setAttribute("open", "");
    form.scrollIntoView({ behavior: "smooth", block: "center" });
    const firstInput = form.querySelector("input:not([type='hidden']), select, textarea");
    if (firstInput) firstInput.focus({ preventScroll: true });
  });
});
