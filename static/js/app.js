// PetroSmart shared behaviour. Kept small: no business logic in the browser.
(function () {
  "use strict";

  document.addEventListener("submit", function (event) {
    var form = event.target;

    // Confirmation before destructive actions: <form data-confirm="Delete this outlet?">
    var message = form.getAttribute("data-confirm");
    if (message && !window.confirm(message)) {
      event.preventDefault();
      return;
    }

    // Loading feedback and protection against double submission.
    var button = form.querySelector('button[type="submit"]:not([data-no-busy])');
    if (button) {
      // Defer so the button's own name/value is still sent with the form.
      window.setTimeout(function () {
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        var busyText = button.getAttribute("data-busy-text");
        if (busyText) button.textContent = busyText;
      }, 0);
    }
  });
})();
