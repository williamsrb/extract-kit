(function () {
  var spec = window.EXTRACTKIT_SPEC;
  var root = document.getElementById("swagger-ui");
  if (typeof SwaggerUIBundle !== "function") {
    root.textContent = "swagger-ui-bundle.js failed to load.";
    return;
  }
  if (!spec) {
    root.textContent = "Missing spec.js. Re-run extractkit integrations / cms --apply.";
    return;
  }
  window.ui = SwaggerUIBundle({
    spec: spec,
    dom_id: "#swagger-ui",
    deepLinking: true,
    tryItOutEnabled: false,
    supportedSubmitMethods: [],
    displayRequestDuration: false,
    filter: true,
    presets: [SwaggerUIBundle.presets.apis],
  });
})();
