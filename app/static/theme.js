(function () {
  var themes = ["sky", "jade", "sunset", "dark"];
  try {
    var saved = localStorage.getItem("airport-monitor-theme");
    document.documentElement.dataset.theme = themes.indexOf(saved) >= 0 ? saved : "sky";
  } catch (_) {
    document.documentElement.dataset.theme = "sky";
  }
})();
