// Purchase (Fuel): live row totals, round off, "Add new" rows, remove and
// info buttons, and tank lists limited to the chosen outlet and item.
// A convenience only: the server recalculates every figure when saving.
(function () {
  "use strict";

  var form = document.querySelector("[data-purchase-form]");
  if (!form) return;
  var table = form.querySelector("[data-lines]");
  var tankMap = JSON.parse(document.getElementById("tank-map").textContent);

  // Whole-number maths: KL in thousandths, money in paise.
  function scaled(text, places) {
    text = (text || "").trim();
    var pattern = new RegExp("^\\d+(\\.\\d{0," + places + "})?$");
    if (!pattern.test(text)) return null;
    var parts = text.split("."), factor = Math.pow(10, places);
    return parseInt(parts[0], 10) * factor + parseInt(((parts[1] || "") + "000").slice(0, places), 10);
  }
  function rupees(paise) {
    var sign = paise < 0 ? "−" : "";
    return sign + "₹" + (Math.abs(paise) / 100).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function litres(milli) {
    return (milli).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  function refresh() {
    var sum = 0, any = false;
    table.querySelectorAll("[data-line]").forEach(function (line) {
      if (line.hidden) return;
      var kl = scaled(line.querySelector("[data-kl]").value, 3);
      var rate = scaled(line.querySelector("[data-rate]").value, 2);
      var out = line.querySelector('[data-out="line-total"]');
      var invoiced = line.querySelector('[data-out="invoiced-litres"]');
      if (invoiced) invoiced.textContent = kl === null ? "—" : litres(kl);
      if (kl === null || rate === null) { out.textContent = "—"; return; }
      var total = Math.round((kl * rate) / 1000);  // KL × rate, rounded to paise
      line.querySelectorAll("[data-charge]").forEach(function (input) {
        var v = scaled(input.value, 2);
        if (v !== null) total += v;
      });
      out.textContent = rupees(total);
      sum += total;
      any = true;
    });
    var roundUp = form.querySelector("[data-round-up]").checked;
    var roundOff = roundUp ? Math.round(sum / 100) * 100 - sum : 0;  // nearest rupee, half up
    form.querySelector('[data-out="lines-total"]').textContent = any ? rupees(sum) : "—";
    form.querySelector('[data-out="round-off"]').textContent = any ? rupees(roundOff) : "—";
    form.querySelector('[data-out="invoice-amount"]').textContent = any ? rupees(sum + roundOff) : "—";
  }

  // Tank list: only tanks at the chosen outlet holding the chosen item.
  function filterTanks(line) {
    var outlet = form.querySelector("[data-purchase-outlet]").value;
    var product = line.querySelector("[data-line-product]").value;
    var select = line.querySelector("[data-line-tank]");
    var matches = [];
    Array.prototype.forEach.call(select.options, function (option) {
      if (!option.value) return;
      var tank = tankMap[option.value];
      var ok = tank && (!outlet || tank.outlet === outlet) && (!product || tank.product === product);
      option.hidden = !ok;
      option.disabled = !ok;
      if (ok) matches.push(option.value);
    });
    if (select.value && matches.indexOf(select.value) === -1) select.value = "";
    if (!select.value && matches.length === 1 && product) select.value = matches[0];
  }
  function filterAll() { table.querySelectorAll("[data-line]").forEach(filterTanks); }

  form.addEventListener("click", function (event) {
    var line = event.target.closest("[data-line]");
    if (event.target.closest("[data-delete-line]")) {
      // Clearing every field makes the server skip the row; hide it from view.
      line.querySelectorAll("input, select").forEach(function (el) { el.value = ""; });
      line.hidden = true;
      refresh();
    }
    var info = event.target.closest("[data-info-line]");
    if (info) {
      var extra = line.querySelector("[data-line-extra]");
      extra.hidden = !extra.hidden;
      info.setAttribute("aria-expanded", extra.hidden ? "false" : "true");
      if (!extra.hidden) extra.querySelector("input").focus();
    }
    if (event.target.closest("[data-add-line]")) {
      var total = form.querySelector('input[name="lines-TOTAL_FORMS"]');
      var html = form.querySelector("template[data-empty-line]").innerHTML.replace(/__prefix__/g, total.value);
      table.querySelector("tfoot").insertAdjacentHTML("beforebegin", html);
      total.value = parseInt(total.value, 10) + 1;
      var added = table.querySelectorAll("[data-line]");
      added = added[added.length - 1];
      filterTanks(added);
      added.querySelector("select").focus();
      refresh();
    }
  });

  form.addEventListener("change", function (event) {
    if (event.target.matches("[data-purchase-outlet]")) filterAll();
    if (event.target.matches("[data-line-product]")) filterTanks(event.target.closest("[data-line]"));
    refresh();
  });
  form.addEventListener("input", refresh);

  filterAll();
  refresh();
})();
