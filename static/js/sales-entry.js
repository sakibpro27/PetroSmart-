// Daily Sales entry: live preview of delivery, net sales and value while typing.
// This is a convenience only. The server recalculates and validates every
// figure on save, using sales/calculations.py.
(function () {
  "use strict";

  var table = document.querySelector("[data-sales-entry]");
  if (!table) return;

  // Work in hundredths (paise / centilitres) as whole numbers to avoid
  // floating-point rounding errors.
  function hundredths(text) {
    text = (text || "").trim();
    if (!/^\d+(\.\d{0,2})?$/.test(text)) return null;
    var parts = text.split(".");
    return parseInt(parts[0], 10) * 100 + parseInt(((parts[1] || "") + "00").slice(0, 2), 10);
  }

  function format(value) {
    if (value === null) return "—";
    return (value / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function input(container, role) {
    return container.querySelector('[data-role="' + role + '"]');
  }

  function rowFigures(row) {
    var extra = document.getElementById(row.dataset.extra);
    var opening = hundredths(row.dataset.opening);
    var price = hundredths(row.dataset.price);
    var closing = hundredths(input(row, "closing").value);
    var testingText = input(row, "testing").value.trim();
    var testing = testingText === "" ? 0 : hundredths(testingText);
    var reset = input(extra, "reset").checked;
    var delivery = null;
    var problem = "";

    if (closing !== null) {
      if (reset) {
        var before = hundredths(input(extra, "before").value);
        var after = hundredths(input(extra, "after").value);
        if (before !== null && after !== null) delivery = (before - opening) + (closing - after);
      } else {
        delivery = closing - opening;
      }
    }
    if (delivery !== null && delivery < 0) {
      problem = reset ? "Check the reset readings: delivery would be negative."
                      : "Closing reading is below the opening reading. Record a meter reset if the meter rolled over or was replaced.";
      delivery = null;
    } else if (testing === null) {
      problem = "Testing litres must be a number with up to 2 decimals.";
    } else if (delivery !== null && testing > delivery) {
      problem = "Testing litres cannot be more than the total nozzle delivery.";
    }

    var net = delivery !== null && testing !== null && !problem ? delivery - testing : null;
    var value = net === null ? null : Math.round((net * price) / 100);
    return { extra: extra, delivery: delivery, net: net, value: value, problem: problem };
  }

  function refresh() {
    var totals = { delivery: 0, net: 0, value: 0 };
    var complete = true;
    table.querySelectorAll(".entry-row").forEach(function (row) {
      var f = rowFigures(row);
      row.querySelector('[data-out="delivery"]').textContent = format(f.delivery);
      row.querySelector('[data-out="net"]').textContent = format(f.net);
      row.querySelector('[data-out="value"]').textContent = f.value === null ? "—" : "₹" + format(f.value);
      f.extra.querySelector('[data-out="problem"]').textContent = f.problem;
      if (f.problem) showExtra(f.extra, true);
      f.extra.querySelectorAll("[data-reset-field]").forEach(function (el) {
        el.hidden = !input(f.extra, "reset").checked;
      });
      if (f.net === null) complete = false;
      else { totals.delivery += f.delivery; totals.net += f.net; totals.value += f.value; }
    });
    table.querySelector('[data-total="delivery"]').textContent = complete ? format(totals.delivery) : "—";
    table.querySelector('[data-total="net"]').textContent = complete ? format(totals.net) : "—";
    table.querySelector('[data-total="value"]').textContent = complete ? "₹" + format(totals.value) : "—";
    refreshPayments(complete ? totals.value : null);
  }

  // Payment breakdown: cash expected = sales value - non-cash payments - credit sales.
  var payments = document.querySelector("[data-payments]");

  function refreshPayments(salesValue) {
    if (!payments) return;
    function amount(input) {
      var value = hundredths(input.value);
      return value === null ? 0 : value;
    }
    var cash = 0, nonCash = 0, credit = 0;
    payments.querySelectorAll("tr[data-kind]").forEach(function (row) {
      var input = row.querySelector('[data-role="amount"]');
      if (row.dataset.kind === "CASH") cash += amount(input); else nonCash += amount(input);
    });
    payments.querySelectorAll('[data-role="credit"]').forEach(function (input) {
      var removed = input.closest("tr").querySelector('input[type="checkbox"]');
      if (!removed || !removed.checked) credit += amount(input);
    });
    function show(key, text) { payments.querySelector('[data-pay="' + key + '"]').textContent = text; }
    show("noncash", "₹" + format(nonCash));
    show("credit", "₹" + format(credit));
    show("cash", "₹" + format(cash));
    if (salesValue === null) {
      ["sales", "expected", "difference"].forEach(function (key) { show(key, "—"); });
      return;
    }
    var expected = salesValue - nonCash - credit;
    var difference = cash - expected;
    show("sales", "₹" + format(salesValue));
    show("expected", "₹" + format(expected));
    show("difference", difference === 0 ? "Matches" : (difference < 0 ? "Short ₹" : "Excess ₹") + format(Math.abs(difference)));
  }

  if (payments) {
    payments.addEventListener("input", refresh);
    payments.addEventListener("change", refresh);
  }

  function showExtra(extra, open) {
    extra.hidden = !open;
    var button = table.querySelector('[data-toggle-extra="' + extra.id + '"]');
    if (button) button.setAttribute("aria-expanded", open ? "true" : "false");
  }

  // Collapse the notes / meter-reset row unless it has content or errors.
  table.querySelectorAll(".entry-extra").forEach(function (extra) {
    showExtra(extra, extra.dataset.keepOpen === "1");
  });
  table.addEventListener("click", function (event) {
    var button = event.target.closest("[data-toggle-extra]");
    if (!button) return;
    var extra = document.getElementById(button.getAttribute("data-toggle-extra"));
    showExtra(extra, extra.hidden);
  });
  table.addEventListener("input", refresh);
  table.addEventListener("change", refresh);

  // Ask before the final submit (not before saving a draft).
  var form = table.closest("form");
  form.addEventListener("submit", function (event) {
    var submitter = event.submitter;
    var message = submitter && submitter.getAttribute("data-confirm-submit");
    if (message && !window.confirm(message)) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  refresh();
})();
