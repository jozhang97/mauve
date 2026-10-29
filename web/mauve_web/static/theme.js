// Apply before loading CSS to avoid a light flash when reopening a dark workspace.
(() => {
  const key = "mauve-theme";
  const system = window.matchMedia("(prefers-color-scheme: dark)");
  const valid = (value) => ["light", "dark", "system"].includes(value);
  let preference = "system";
  try {
    const saved = localStorage.getItem(key);
    if (valid(saved)) preference = saved;
  } catch {}
  function apply() {
    document.documentElement.dataset.theme =
      preference === "system"
        ? system.matches
          ? "dark"
          : "light"
        : preference;
    const control = document.getElementById("theme");
    if (control) control.value = preference;
  }
  apply();
  system.addEventListener("change", apply);
  window.addEventListener("storage", (event) => {
    if (event.key === key || event.key === null) {
      preference = valid(event.newValue) ? event.newValue : "system";
      apply();
    }
  });
  document.addEventListener("DOMContentLoaded", () => {
    apply();
    document.getElementById("theme").addEventListener("change", (event) => {
      preference = event.target.value;
      try {
        localStorage.setItem(key, preference);
      } catch {}
      apply();
    });
  });
})();
