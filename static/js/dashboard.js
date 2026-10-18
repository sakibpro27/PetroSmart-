// Dashboard charts (Chart.js). Colours come from the CSS tokens so the palette
// stays in one place. Every chart has a table version in the page.
(function () {
  "use strict";
  if (typeof Chart === "undefined") return; // CDN unavailable: the tables still show the data

  var css = getComputedStyle(document.documentElement);
  function token(name) { return css.getPropertyValue(name).trim(); }
  function data(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }
  function litres(value) {
    return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + " L";
  }
  function rupees(value) {
    return "₹" + value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  Chart.defaults.font.family = token("--ps-font");
  Chart.defaults.color = token("--ps-chart-axis");
  var grid = { color: token("--ps-chart-grid"), drawTicks: false };
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var tooltip = {
    backgroundColor: token("--ps-white"), titleColor: token("--ps-text"), bodyColor: token("--ps-text"),
    borderColor: token("--ps-border-strong"), borderWidth: 1, padding: 10, boxPadding: 4,
  };

  var sales = data("sales-chart-data");
  var salesCanvas = document.getElementById("sales-chart");
  if (sales && salesCanvas) {
    new Chart(salesCanvas, {
      type: "bar",
      data: {
        labels: sales.labels,
        datasets: [
          { label: "MS (Petrol)", data: sales.ms, backgroundColor: token("--ps-chart-ms") },
          { label: "HSD (Diesel)", data: sales.hsd, backgroundColor: token("--ps-chart-hsd") },
        ],
      },
      options: {
        maintainAspectRatio: false,
        animation: reduceMotion ? false : { duration: 300 },
        // Thin bars with a 2px gap between neighbours and rounded data ends.
        datasets: { bar: { borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "bottom",
                           maxBarThickness: 18, categoryPercentage: 0.7, barPercentage: 0.9,
                           borderColor: token("--ps-white"), borderWidth: { left: 1, right: 1 } } },
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: { display: false }, // the legend is in the card header, as HTML
          tooltip: Object.assign({}, tooltip, { callbacks: { label: function (c) { return c.dataset.label + ": " + litres(c.parsed.y); } } }),
        },
        scales: {
          x: { grid: { display: false }, border: { display: false } },
          y: { beginAtZero: true, grid: grid, border: { display: false },
               ticks: { callback: function (v) { return v.toLocaleString("en-IN"); } } },
        },
      },
    });
  }

  var pay = data("payments-chart-data");
  var payCanvas = document.getElementById("payments-chart");
  if (pay && payCanvas) {
    new Chart(payCanvas, {
      type: "bar",
      data: { labels: pay.labels, datasets: [{ label: "Amount", data: pay.values, backgroundColor: token("--ps-chart-ms") }] },
      options: {
        indexAxis: "y",
        maintainAspectRatio: false,
        animation: reduceMotion ? false : { duration: 300 },
        datasets: { bar: { borderRadius: { topRight: 4, bottomRight: 4 }, borderSkipped: "left", maxBarThickness: 14 } },
        plugins: {
          legend: { display: false }, // one series: the card title names it
          tooltip: Object.assign({}, tooltip, { callbacks: { label: function (c) { return rupees(c.parsed.x); } } }),
        },
        scales: {
          x: { beginAtZero: true, grid: grid, border: { display: false },
               ticks: { callback: function (v) { return "₹" + v.toLocaleString("en-IN"); } } },
          y: { grid: { display: false }, border: { display: false } },
        },
      },
    });
  }
})();
