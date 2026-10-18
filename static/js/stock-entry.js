// Tank stock entry: live preview of the variation while the dip stock is typed.
// The server recalculates it on save (stock/calculations.py).
(function () {
  "use strict";

  var table = document.querySelector("[data-stock-entry]");
  if (!table) return;

  function hundredths(text) {
    text = (text || "").trim();
    if (!/^-?\d+(\.\d{0,2})?$/.test(text)) return null;
    var negative = text.charAt(0) === "-";
    var parts = text.replace("-", "").split(".");
    var value = parseInt(parts[0], 10) * 100 + parseInt(((parts[1] || "") + "00").slice(0, 2), 10);
    return negative ? -value : value;
  }

  function format(value) {
    return (value / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function refresh(row) {
    var measured = hundredths(row.querySelector('[data-role="measured"]').value);
    var out = row.querySelector('[data-out="variation"]');
    if (measured === null) { out.textContent = "—"; return; }
    var variation = measured - hundredths(row.dataset.calculated);
    var flagged = Math.abs(variation) > hundredths(row.dataset.alert);
    out.innerHTML = "";
    var span = document.createElement("span");
    span.textContent = format(variation);
    if (flagged) {
      span.className = "status status-danger";
      span.textContent = "Beyond limit: " + format(variation);
    }
    out.appendChild(span);
  }

  table.addEventListener("input", function (event) {
    var row = event.target.closest("tr");
    if (row && row.dataset.calculated) refresh(row);
  });
})();
