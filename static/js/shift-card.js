// Shift Card: live totals while typing, "Add item" rows, and loading the pump
// rows when date, shift and MPD/DU are chosen. This is a convenience only:
// the server recalculates and validates every figure when the card is saved.
(function () {
  "use strict";

  var form = document.querySelector("[data-shift-card]");
  if (!form) return;
  var table = form.querySelector("[data-sales-entry]");

  // Work in hundredths (paise / centilitres) as whole numbers to avoid rounding errors.
  function hundredths(text) {
    text = (text || "").trim();
    if (!/^\d+(\.\d{0,2})?$/.test(text)) return null;
    var parts = text.split(".");
    return parseInt(parts[0], 10) * 100 + parseInt(((parts[1] || "") + "00").slice(0, 2), 10);
  }
  function value(input) { var v = input ? hundredths(input.value) : null; return v === null ? 0 : v; }
  function format(v) {
    return (v / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function rupees(v) { return (v < 0 ? "−₹" : "₹") + format(Math.abs(v)); }
  function role(container, name) { return container.querySelector('[data-role="' + name + '"]'); }

  // --- Pump rows -------------------------------------------------------------
  function showExtra(extra, open) {
    extra.hidden = !open;
    var button = table.querySelector('[data-toggle-extra="' + extra.id + '"]');
    if (button) button.setAttribute("aria-expanded", open ? "true" : "false");
  }

  function pumpTotals() {
    var totals = { delivery: 0, testing: 0, net: 0, value: 0 }, complete = true, any = false;
    table.querySelectorAll(".entry-row").forEach(function (row) {
      any = true;
      var extra = document.getElementById(row.dataset.extra);
      var opening = hundredths(row.dataset.opening), price = hundredths(row.dataset.price);
      var closing = hundredths(role(row, "closing").value);
      var testingText = role(row, "testing").value.trim();
      var testing = testingText === "" ? 0 : hundredths(testingText);
      var reset = role(extra, "reset").checked, delivery = null, problem = "";
      if (closing !== null) {
        if (reset) {
          var before = hundredths(role(extra, "before").value), after = hundredths(role(extra, "after").value);
          if (before !== null && after !== null) delivery = (before - opening) + (closing - after);
        } else {
          delivery = closing - opening;
        }
      }
      if (delivery !== null && delivery < 0) {
        problem = reset ? "Check the reset readings: sale would be negative."
                        : "Closing is below opening. Record a meter reset if the meter rolled over or was replaced.";
        delivery = null;
      } else if (testing === null) {
        problem = "Testing litres must be a number with up to 2 decimals.";
      } else if (delivery !== null && testing > delivery) {
        problem = "Testing litres cannot be more than the Sale Ltr.";
      }
      var net = delivery !== null && testing !== null && !problem ? delivery - testing : null;
      var amount = net === null ? null : Math.round((net * price) / 100);
      row.querySelector('[data-out="delivery"]').textContent = delivery === null ? "—" : format(delivery);
      row.querySelector('[data-out="net"]').textContent = net === null ? "—" : format(net);
      row.querySelector('[data-out="value"]').textContent = amount === null ? "—" : format(amount);
      extra.querySelector('[data-out="problem"]').textContent = problem;
      if (problem) showExtra(extra, true);
      extra.querySelectorAll("[data-reset-field]").forEach(function (el) { el.hidden = !reset; });
      if (net === null) complete = false;
      else { totals.delivery += delivery; totals.testing += testing; totals.net += net; totals.value += amount; }
    });
    ["delivery", "testing", "net"].forEach(function (key) {
      table.querySelector('[data-total="' + key + '"]').textContent = complete && any ? format(totals[key]) : "—";
    });
    table.querySelector('[data-total="value"]').textContent = complete && any ? rupees(totals.value) : "—";
    return complete && any ? totals.value : null;
  }

  // --- Money details and detail rows ---------------------------------------------
  function cashCollection() {
    var total = 0;
    form.querySelectorAll("[data-note]").forEach(function (input) {
      var note = parseInt(input.dataset.note, 10), count = parseInt(input.value, 10);
      var amount = isNaN(count) || count < 0 ? 0 : count * note * 100;
      var out = form.querySelector('[data-note-amount="' + note + '"]');
      if (out) out.textContent = format(amount);
      total += amount;
    });
    total += value(form.querySelector('[data-money="coins"]'));
    form.querySelector("[data-money-total]").textContent = rupees(total);
    return total;
  }

  function detailTotal(key) {
    var section = form.querySelector('[data-detail="' + key + '"]'), total = 0;
    if (!section) return 0;
    if (key === "lubes") {
      section.querySelectorAll("[data-rows] tr").forEach(function (row) {
        total += Math.round(value(row.querySelector("[data-qty]")) * value(row.querySelector("[data-rate]")) / 100);
      });
    } else {
      section.querySelectorAll("[data-sum]").forEach(function (input) { total += value(input); });
    }
    section.querySelector("[data-detail-total]").textContent = total ? "· " + rupees(total) : "";
    return total;
  }

  function show(key, amount) {
    var out = form.querySelector('[data-sum-out="' + key + '"]');
    if (out) out.textContent = amount === null ? "—" : rupees(amount);
    return out;
  }

  function refresh() {
    var fuel = table ? pumpTotals() : null;
    var cash = cashCollection();
    var parts = {};
    ["lubes", "receipts", "credit", "expenses"].forEach(function (key) { parts[key] = detailTotal(key); });
    var cards = ["general_credit", "bank_card", "company_card", "phone_wallet"].reduce(function (sum, name) {
      return sum + value(form.querySelector('[data-money="' + name + '"]'));
    }, 0);
    show("fuel", fuel);
    show("lubes", parts.lubes);
    show("receipts", parts.receipts);
    show("cash", cash);
    show("credit", parts.credit);
    show("expenses", parts.expenses);
    if (fuel === null) { show("balance", null); return; }
    var expected = fuel + parts.lubes + parts.receipts - parts.credit - cards - parts.expenses;
    var balance = cash - expected;
    var out = show("balance", balance);
    out.textContent = balance === 0 ? "₹0.00 (matches)" : (balance < 0 ? "Short " : "Excess ") + rupees(Math.abs(balance));
    out.classList.toggle("is-short", balance < 0);
  }

  // "Add item": copy the empty row, numbering it after the existing rows.
  form.querySelectorAll("[data-detail]").forEach(function (section) {
    var key = section.dataset.detail;
    section.hidden = section.dataset.keepOpen !== "1";
    section.querySelector("[data-add-row]").addEventListener("click", function () {
      var total = form.querySelector('input[name="' + key + '-TOTAL_FORMS"]');
      var html = section.querySelector("template[data-empty-row]").innerHTML.replace(/__prefix__/g, total.value);
      section.querySelector("[data-rows]").insertAdjacentHTML("beforeend", html);
      total.value = parseInt(total.value, 10) + 1;
      var first = section.querySelector("[data-rows] tr:last-child select, [data-rows] tr:last-child input");
      if (first) first.focus();
    });
  });
  form.addEventListener("click", function (event) {
    var open = event.target.closest("[data-open]");
    if (open) {
      var section = form.querySelector('[data-detail="' + open.dataset.open + '"]');
      section.hidden = false;
      section.scrollIntoView({ behavior: "smooth", block: "center" });
      var field = section.querySelector("select, input:not([type=hidden])");
      if (field) field.focus({ preventScroll: true });
    }
    var clear = event.target.closest("[data-clear-row]");
    if (clear) {
      clear.closest("tr").querySelectorAll("input, select").forEach(function (el) { el.value = ""; });
      refresh();
    }
    var toggle = event.target.closest("[data-toggle-extra]");
    if (toggle) {
      var extra = document.getElementById(toggle.getAttribute("data-toggle-extra"));
      showExtra(extra, extra.hidden);
    }
  });

  // Lube rows: fill the rate from the item's selling price.
  var pricesEl = document.getElementById("lube-prices");
  var prices = pricesEl ? JSON.parse(pricesEl.textContent) : {};
  form.addEventListener("change", function (event) {
    var select = event.target;
    if (select.name && /^lubes-\d+-item$/.test(select.name)) {
      var rate = select.closest("tr").querySelector("[data-rate]");
      if (rate && !rate.value && prices[select.value]) rate.value = prices[select.value];
    }
  });

  if (table) {
    table.querySelectorAll(".entry-extra").forEach(function (extra) { showExtra(extra, extra.dataset.keepOpen === "1"); });
  }
  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);

  // New card: choosing date, shift and MPD/DU reloads the page with that pump's rows.
  if (form.hasAttribute("data-new-card")) {
    ["business_date", "shift", "dispenser"].forEach(function (name) {
      var field = form.querySelector('[name="' + name + '"]');
      if (!field) return;
      field.addEventListener("change", function () {
        var params = new URLSearchParams();
        ["business_date", "shift", "dispenser"].forEach(function (n) {
          var f = form.querySelector('[name="' + n + '"]');
          if (f && f.value) params.set(n, f.value);
        });
        if (params.has("business_date") && params.has("shift") && params.has("dispenser")) {
          window.location.search = params.toString();
        }
      });
    });
  }

  refresh();
})();
