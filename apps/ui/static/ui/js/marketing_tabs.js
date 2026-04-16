(function () {
  document.querySelectorAll("[data-tab-group]").forEach(function (root) {
    var tabs = root.querySelectorAll(".mk-tab[data-tab]");
    var panels = root.querySelectorAll(".mk-tab-panel[data-panel]");
    function activate(name) {
      tabs.forEach(function (btn) {
        var on = btn.getAttribute("data-tab") === name;
        btn.classList.toggle("mk-tab-active", on);
        btn.setAttribute("aria-selected", on ? "true" : "false");
        if (on) btn.classList.remove("text-slate-400");
        else btn.classList.add("text-slate-400");
      });
      panels.forEach(function (panel) {
        var show = panel.getAttribute("data-panel") === name;
        panel.classList.toggle("hidden", !show);
        panel.hidden = !show;
      });
    }
    tabs.forEach(function (btn) {
      btn.addEventListener("click", function () {
        activate(btn.getAttribute("data-tab"));
      });
    });
  });
})();
