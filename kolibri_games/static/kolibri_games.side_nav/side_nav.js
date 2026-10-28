/* Adds "Games" to Kolibri's side menu. Hand-written, so the plugin needs no
 * JavaScript build step. It uses the same shared module that Kolibri's own
 * plugins use for their menu entries; if that isn't there (a different
 * Kolibri version), it quietly does nothing. */
(function () {
  "use strict";
  var BUNDLE = "kolibri_games.side_nav";
  try {
    var template = document.querySelector('template[data-plugin="' + BUNDLE + '"]');
    var data = template ? JSON.parse(template.innerHTML.trim() || "{}") : {};
    var core = window.kolibriCoreAppGlobal;
    var nav = core && core["kolibri/composables/useNav"];
    if (!data.url || !nav || typeof nav.registerNavItem !== "function") return;
    nav.registerNavItem({
      url: data.url,
      label: data.label || "Games",
      icon: "star"
    });
  } catch (e) {
    if (window.console) console.warn("Kolibri Games: couldn't add the menu link", e);
  }
})();
