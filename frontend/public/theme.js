// Aplica o tema guardado antes da primeira pintura, para a tela não piscar clara.
try {
  const stored = localStorage.getItem("notai-theme");
  if (stored === "light" || stored === "dark") {
    document.documentElement.dataset.theme = stored;
  }
} catch (error) {
  void error;
}
