(function () {
  var key = "skymailr_marketing_theme";
  function apply(theme) {
    document.documentElement.setAttribute("data-mk-theme", theme);
    try {
      localStorage.setItem(key, theme);
    } catch (e) {}
    var lightBtn = document.getElementById("mk-theme-light");
    var darkBtn = document.getElementById("mk-theme-dark");
    if (lightBtn && darkBtn) {
      var isLight = theme === "light";
      lightBtn.classList.toggle("mk-theme-active", isLight);
      darkBtn.classList.toggle("mk-theme-active", !isLight);
      lightBtn.setAttribute("aria-pressed", isLight ? "true" : "false");
      darkBtn.setAttribute("aria-pressed", isLight ? "false" : "true");
    }
  }
  function initial() {
    try {
      var stored = localStorage.getItem(key);
      if (stored === "light" || stored === "dark") return stored;
    } catch (e) {}
    return "light";
  }
  apply(initial());
  document.getElementById("mk-theme-light")?.addEventListener("click", function () {
    apply("light");
  });
  document.getElementById("mk-theme-dark")?.addEventListener("click", function () {
    apply("dark");
  });
})();
